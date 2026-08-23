import hashlib
import hmac
import json
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse


MAX_BODY_BYTES = 64 * 1024
MAX_CLOCK_SKEW_SECONDS = 120
NONCE_TTL_SECONDS = 300


class AuthenticationError(Exception):
    pass


class ReplayError(AuthenticationError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ManagerState:
    def __init__(self, sites: list[dict[str, str]], offline_seconds: int = 150):
        self.offline_seconds = offline_seconds
        self._lock = threading.Lock()
        self._sites_by_code = {site["site_code"]: dict(site) for site in sites}
        self._site_code_by_key = {site["agent_key_id"]: site["site_code"] for site in sites}
        self._latest: dict[str, dict[str, Any]] = {}
        self._seen_nonces: dict[tuple[str, str], datetime] = {}

    def authenticate_request(
        self,
        key_id: str,
        timestamp: str,
        nonce: str,
        signature: str,
        method: str,
        path: str,
        body: bytes,
        now: datetime | None = None,
    ) -> dict[str, str]:
        site_code = self._site_code_by_key.get(key_id)
        if not site_code or not timestamp or not nonce or not signature:
            raise AuthenticationError("Invalid agent authentication")
        if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", nonce):
            raise AuthenticationError("Invalid agent authentication")
        if not re.fullmatch(r"[0-9a-f]{64}", signature):
            raise AuthenticationError("Invalid agent authentication")
        try:
            request_time = datetime.fromtimestamp(int(timestamp), timezone.utc)
        except (ValueError, OverflowError):
            raise AuthenticationError("Invalid agent authentication") from None
        current = now or utc_now()
        if abs((current - request_time).total_seconds()) > MAX_CLOCK_SKEW_SECONDS:
            raise AuthenticationError("Agent request timestamp is outside the allowed window")

        site = self._sites_by_code[site_code]
        body_sha256 = hashlib.sha256(body).hexdigest()
        canonical = "\n".join((method.upper(), path, timestamp, nonce, body_sha256)).encode("utf-8")
        expected = hmac.new(bytes.fromhex(site["secret_sha256"]), canonical, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise AuthenticationError("Invalid agent authentication")

        nonce_key = (key_id, nonce)
        with self._lock:
            self._seen_nonces = {key: expires for key, expires in self._seen_nonces.items() if expires > current}
            if nonce_key in self._seen_nonces:
                raise ReplayError("Agent request nonce has already been used")
            self._seen_nonces[nonce_key] = current.replace(microsecond=0) + timedelta(seconds=NONCE_TTL_SECONDS)
        return site

    def update(self, identity: dict[str, str], payload: dict[str, Any], received_at: datetime | None = None) -> None:
        if payload.get("site_code") != identity["site_code"]:
            raise PermissionError("Credential is not valid for this site")
        if payload.get("device_uid") != identity["device_uid"]:
            raise PermissionError("Credential is not valid for this device")
        required_fields = {"observed_at", "agent_version", "cpu_percent", "ram_percent", "disk_percent"}
        missing = sorted(required_fields.difference(payload))
        if missing:
            raise ValueError(f"Missing fields: {', '.join(missing)}")
        snapshot = dict(payload)
        snapshot["received_at"] = (received_at or utc_now()).isoformat()
        with self._lock:
            self._latest[identity["site_code"]] = snapshot

    def sites(self, now: datetime | None = None) -> list[dict[str, Any]]:
        current = now or utc_now()
        result = []
        with self._lock:
            latest = {key: dict(value) for key, value in self._latest.items()}
        for site_code in sorted(self._sites_by_code):
            config = self._sites_by_code[site_code]
            snapshot = latest.get(site_code)
            online = False
            if snapshot:
                received_at = datetime.fromisoformat(snapshot["received_at"])
                online = (current - received_at).total_seconds() <= self.offline_seconds
            result.append(
                {
                    "site_code": site_code,
                    "site_name": config["site_name"],
                    "device_uid": config["device_uid"],
                    "status": "online" if online else "offline",
                    "remote_url": config.get("remote_url", ""),
                    "last_seen": snapshot.get("received_at") if snapshot else None,
                    "ha_version": snapshot.get("ha_version") if snapshot else None,
                    "agent_version": snapshot.get("agent_version") if snapshot else None,
                    "cpu_percent": snapshot.get("cpu_percent") if snapshot else None,
                    "ram_percent": snapshot.get("ram_percent") if snapshot else None,
                    "disk_percent": snapshot.get("disk_percent") if snapshot else None,
                    "tunnel_status": snapshot.get("tunnel_status") if snapshot else "not_configured",
                }
            )
        return result


def send_json(handler: BaseHTTPRequestHandler, status: int, payload: object) -> None:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.end_headers()
    handler.wfile.write(body)


def read_body(handler: BaseHTTPRequestHandler, allow_empty: bool = False) -> bytes:
    try:
        length = int(handler.headers.get("Content-Length", "0"))
    except ValueError as exc:
        raise ValueError("Invalid Content-Length") from exc
    if length < 0 or length > MAX_BODY_BYTES or (length == 0 and not allow_empty):
        raise ValueError("Request body size is invalid")
    return handler.rfile.read(length) if length else b""


def parse_json(body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError("Request body must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object")
    return payload


def agent_handler_factory(state: ManagerState):
    class AgentHandler(BaseHTTPRequestHandler):
        server_version = "HAFleetAgentAPI/0.1"

        def do_GET(self) -> None:
            if urlparse(self.path).path == "/healthz":
                send_json(self, HTTPStatus.OK, {"status": "ok"})
                return
            send_json(self, HTTPStatus.NOT_FOUND, {"detail": "Not found"})

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            if path not in {"/api/agent/register", "/api/agent/heartbeat"}:
                send_json(self, HTTPStatus.NOT_FOUND, {"detail": "Not found"})
                return
            try:
                body = read_body(self, allow_empty=path == "/api/agent/register")
                identity = state.authenticate_request(
                    self.headers.get("X-Agent-Key-Id", ""),
                    self.headers.get("X-Agent-Timestamp", ""),
                    self.headers.get("X-Agent-Nonce", ""),
                    self.headers.get("X-Agent-Signature", ""),
                    "POST",
                    path,
                    body,
                )
            except ReplayError as exc:
                send_json(self, HTTPStatus.CONFLICT, {"detail": str(exc)})
                return
            except AuthenticationError as exc:
                send_json(self, HTTPStatus.UNAUTHORIZED, {"detail": str(exc)})
                return
            except ValueError as exc:
                send_json(self, HTTPStatus.BAD_REQUEST, {"detail": str(exc)})
                return
            if path == "/api/agent/register":
                send_json(
                    self,
                    HTTPStatus.OK,
                    {
                        "site_code": identity["site_code"],
                        "device_uid": identity["device_uid"],
                        "heartbeat_seconds": 60,
                    },
                )
                return
            if path == "/api/agent/heartbeat":
                try:
                    state.update(identity, parse_json(body))
                except PermissionError as exc:
                    send_json(self, HTTPStatus.FORBIDDEN, {"detail": str(exc)})
                    return
                except ValueError as exc:
                    send_json(self, HTTPStatus.BAD_REQUEST, {"detail": str(exc)})
                    return
                send_json(self, HTTPStatus.OK, {"accepted": True, "received_at": utc_now().isoformat()})
                return
        def log_message(self, format_string: str, *args: object) -> None:
            print(f"agent-api {self.client_address[0]} {format_string % args}", flush=True)

    return AgentHandler


def portal_html() -> bytes:
    return r'''<!doctype html>
<html lang="zh-Hant-TW">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>HA Fleet Manager</title>
  <style>
    :root{color-scheme:dark;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;background:#101418;color:#e9f0f4}
    *{box-sizing:border-box}body{margin:0}main{max-width:1100px;margin:auto;padding:24px}
    header{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px}h1{font-size:26px;margin:0}button,a.action{border:0;border-radius:8px;padding:10px 14px;background:#03a9d9;color:#00151d;font-weight:700;text-decoration:none;cursor:pointer}
    .summary{display:flex;gap:12px;margin-bottom:16px}.summary div,.site{background:#1b2228;border:1px solid #33404a;border-radius:12px;padding:16px}.summary strong{font-size:24px;display:block}.summary span,.muted{color:#9fb0bb}
    #sites{display:grid;gap:12px}.site{display:grid;grid-template-columns:minmax(160px,1fr) 2fr auto;gap:16px;align-items:center}.site h2{margin:0 0 5px;font-size:19px}.metrics{display:flex;gap:18px;flex-wrap:wrap}.status{display:inline-flex;align-items:center;gap:7px}.dot{width:10px;height:10px;border-radius:50%;background:#65747d}.online .dot{background:#28c76f}.offline .dot{background:#f05b61}.disabled{pointer-events:none;opacity:.45}
    @media(max-width:700px){.site{grid-template-columns:1fr}.metrics{gap:10px}.site .action{justify-self:start}}
  </style>
</head>
<body><main>
  <header><div><h1>HA Fleet Manager</h1><div class="muted">遠端使用與維修</div></div><button id="refresh">重新整理</button></header>
  <section class="summary"><div><strong id="online">0</strong><span>在線</span></div><div><strong id="offline">0</strong><span>離線</span></div></section>
  <section id="sites"><div class="site">正在取得 SITE 狀態…</div></section>
</main><script>
const esc=value=>String(value??'').replace(/[&<>'"]/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
const pct=value=>value==null?'—':`${Number(value).toFixed(1)}%`;
const time=value=>value?new Date(value).toLocaleString('zh-TW'):'尚未回報';
async function load(){
  const response=await fetch('api/sites',{cache:'no-store'});
  if(!response.ok)throw new Error(`API ${response.status}`);
  const sites=await response.json();
  document.getElementById('online').textContent=sites.filter(site=>site.status==='online').length;
  document.getElementById('offline').textContent=sites.filter(site=>site.status!=='online').length;
  document.getElementById('sites').innerHTML=sites.map(site=>{
    const enabled=site.status==='online'&&site.remote_url;
    const action=site.remote_url?`<a class="action ${enabled?'':'disabled'}" href="${esc(site.remote_url)}" target="_blank" rel="noopener noreferrer">開啟 HA</a>`:'<span class="muted">尚未設定遠端網址</span>';
    return `<article class="site"><div><h2>${esc(site.site_name)}</h2><div class="status ${esc(site.status)}"><span class="dot"></span>${site.status==='online'?'在線':'離線'}</div></div><div><div class="metrics"><span>HA ${esc(site.ha_version||'—')}</span><span>Agent ${esc(site.agent_version||'—')}</span><span>CPU ${pct(site.cpu_percent)}</span><span>RAM ${pct(site.ram_percent)}</span><span>磁碟 ${pct(site.disk_percent)}</span></div><div class="muted">最後更新：${esc(time(site.last_seen))}</div></div>${action}</article>`;
  }).join('')||'<div class="site">尚未設定 SITE</div>';
}
document.getElementById('refresh').onclick=()=>load().catch(showError);
function showError(error){document.getElementById('sites').innerHTML=`<div class="site">無法取得狀態：${esc(error.message)}</div>`}
load().catch(showError);setInterval(()=>load().catch(showError),30000);
</script></body></html>'''.encode("utf-8")


def ui_handler_factory(state: ManagerState):
    html = portal_html()

    class UiHandler(BaseHTTPRequestHandler):
        server_version = "HAFleetManagerUI/0.1"

        def do_GET(self) -> None:
            path = urlparse(self.path).path.rstrip("/") or "/"
            if path == "/api/sites" or path.endswith("/api/sites"):
                send_json(self, HTTPStatus.OK, state.sites())
                return
            if path == "/healthz" or path.endswith("/healthz"):
                send_json(self, HTTPStatus.OK, {"status": "ok"})
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "SAMEORIGIN")
            self.end_headers()
            self.wfile.write(html)

        def log_message(self, format_string: str, *args: object) -> None:
            print(f"manager-ui {self.client_address[0]} {format_string % args}", flush=True)

    return UiHandler


def load_state() -> ManagerState:
    sites = json.loads(os.environ["FLEET_MANAGER_SITES"])
    return ManagerState(sites, int(os.getenv("FLEET_MANAGER_OFFLINE_SECONDS", "150")))


def run() -> None:
    state = load_state()
    ui_server = ThreadingHTTPServer(("0.0.0.0", 8098), ui_handler_factory(state))
    agent_server = ThreadingHTTPServer(("0.0.0.0", 8099), agent_handler_factory(state))
    threading.Thread(target=ui_server.serve_forever, name="manager-ui", daemon=True).start()
    print("HA Fleet Manager UI started on ingress port 8098", flush=True)
    print("HA Fleet Agent API started on port 8099", flush=True)
    try:
        agent_server.serve_forever()
    finally:
        ui_server.shutdown()
        ui_server.server_close()
        agent_server.server_close()


if __name__ == "__main__":
    run()

