import hashlib
import hmac
import json
import os
import re
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


MAX_BODY_BYTES = 16 * 1024
MAX_CLOCK_SKEW_SECONDS = 120
NONCE_TTL_SECONDS = 300
SOCKET = os.getenv("TAILSCALE_SOCKET", "/var/run/tailscale/tailscaled.sock")
CONTROL_KEY_ID = os.environ["TUNNEL_CONTROL_KEY_ID"]
CONTROL_SECRET_SHA256 = os.environ["TUNNEL_CONTROL_SECRET_SHA256"]
SERVE_PORT = int(os.getenv("TAILSCALE_SERVE_PORT", "443"))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TunnelCommandError(RuntimeError):
    pass


class ReplayGuard:
    def __init__(self):
        self._lock = threading.Lock()
        self._seen: dict[str, datetime] = {}

    def accept(self, nonce: str, now: datetime) -> bool:
        with self._lock:
            self._seen = {key: expires for key, expires in self._seen.items() if expires > now}
            if nonce in self._seen:
                return False
            self._seen[nonce] = now + timedelta(seconds=NONCE_TTL_SECONDS)
            return True


def verify_request(headers, method: str, path: str, body: bytes, replay_guard: ReplayGuard, now: datetime | None = None) -> None:
    key_id = headers.get("X-Tunnel-Key-Id", "")
    timestamp = headers.get("X-Tunnel-Timestamp", "")
    nonce = headers.get("X-Tunnel-Nonce", "")
    signature = headers.get("X-Tunnel-Signature", "")
    if key_id != CONTROL_KEY_ID or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", nonce) or not re.fullmatch(r"[0-9a-f]{64}", signature):
        raise PermissionError("Invalid Tunnel authentication")
    try:
        request_time = datetime.fromtimestamp(int(timestamp), timezone.utc)
    except (ValueError, OverflowError):
        raise PermissionError("Invalid Tunnel authentication") from None
    current = now or utc_now()
    if abs((current - request_time).total_seconds()) > MAX_CLOCK_SKEW_SECONDS:
        raise PermissionError("Tunnel request timestamp is outside the allowed window")
    body_hash = hashlib.sha256(body).hexdigest()
    canonical = "\n".join((method.upper(), path, timestamp, nonce, body_hash)).encode("utf-8")
    expected = hmac.new(bytes.fromhex(CONTROL_SECRET_SHA256), canonical, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise PermissionError("Invalid Tunnel authentication")
    if not replay_guard.accept(nonce, current):
        raise FileExistsError("Tunnel request nonce has already been used")


def find_proxy_target(value):
    if isinstance(value, dict):
        for key, child in value.items():
            found = find_proxy_target(child)
            if found:
                return found
            if isinstance(key, str) and "127.0.0.1:8123" in key:
                return key
    elif isinstance(value, list):
        for child in value:
            found = find_proxy_target(child)
            if found:
                return found
    elif isinstance(value, str) and "127.0.0.1:8123" in value:
        return value
    return None


def parse_serve_status(serve_payload: dict, tailscale_payload: dict) -> dict[str, str]:
    if not find_proxy_target(serve_payload):
        return {"status": "OFF", "remote_url": ""}
    dns_name = str(tailscale_payload.get("Self", {}).get("DNSName", "")).rstrip(".")
    if not dns_name:
        raise TunnelCommandError("Tailscale status did not provide a DNS name")
    suffix = "" if SERVE_PORT == 443 else f":{SERVE_PORT}"
    return {"status": "ON", "remote_url": f"https://{dns_name}{suffix}"}


class TailscaleRunner:
    def _run(self, *args: str, allow_failure: bool = False) -> subprocess.CompletedProcess:
        result = subprocess.run(["tailscale", "--socket", SOCKET, *args], capture_output=True, text=True)
        if result.returncode and not allow_failure:
            detail = (result.stderr or result.stdout or "unknown tailscale error").strip()
            raise TunnelCommandError(detail)
        return result

    def enable(self) -> dict[str, str]:
        self._run("serve", "--bg", f"--https={SERVE_PORT}", "http://127.0.0.1:8123")
        return self.status()

    def disable(self) -> dict[str, str]:
        self._run("serve", f"--https={SERVE_PORT}", "off")
        return self.status()

    def status(self) -> dict[str, str]:
        serve = self._run("serve", "status", "--json", allow_failure=True)
        serve_payload = json.loads(serve.stdout) if serve.returncode == 0 and serve.stdout.strip() else {}
        node_payload = json.loads(self._run("status", "--json").stdout)
        return parse_serve_status(serve_payload, node_payload)


def send_json(handler: BaseHTTPRequestHandler, status: int, payload: object) -> None:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.end_headers()
    handler.wfile.write(body)


def handler_factory(runner: TailscaleRunner, replay_guard: ReplayGuard):
    class Handler(BaseHTTPRequestHandler):
        server_version = "HAFleetTunnel/0.1"

        def _authorize(self, method: str, path: str, body: bytes = b"") -> bool:
            try:
                verify_request(self.headers, method, path, body, replay_guard)
                return True
            except FileExistsError as exc:
                send_json(self, HTTPStatus.CONFLICT, {"detail": str(exc)})
            except PermissionError as exc:
                send_json(self, HTTPStatus.UNAUTHORIZED, {"detail": str(exc)})
            return False

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/healthz":
                send_json(self, HTTPStatus.OK, {"status": "ok"})
                return
            if path != "/status" or not self._authorize("GET", path):
                if path != "/status":
                    send_json(self, HTTPStatus.NOT_FOUND, {"detail": "Not found"})
                return
            try:
                send_json(self, HTTPStatus.OK, runner.status())
            except (TunnelCommandError, ValueError, json.JSONDecodeError) as exc:
                send_json(self, HTTPStatus.BAD_GATEWAY, {"status": "ERROR", "detail": str(exc)})

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            if path not in {"/enable", "/disable"}:
                send_json(self, HTTPStatus.NOT_FOUND, {"detail": "Not found"})
                return
            if not self._authorize("POST", path):
                return
            try:
                result = runner.enable() if path == "/enable" else runner.disable()
                send_json(self, HTTPStatus.OK, result)
            except (TunnelCommandError, ValueError, json.JSONDecodeError) as exc:
                send_json(self, HTTPStatus.BAD_GATEWAY, {"status": "ERROR", "detail": str(exc)})

        def log_message(self, format_string: str, *args: object) -> None:
            print(f"tunnel-api {self.client_address[0]} {format_string % args}", flush=True)

    return Handler


def run() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", 9090), handler_factory(TailscaleRunner(), ReplayGuard()))
    print("HA Fleet Tunnel control API started on internal port 9090", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    run()

