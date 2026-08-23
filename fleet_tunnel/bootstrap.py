import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path


SOCKET = "/var/run/tailscale/tailscaled.sock"
AUTH_KEY_PATH = Path("/run/ha-fleet-tunnel/authkey")


class TailscaleAuthenticationError(RuntimeError):
    pass


def required(options: dict, key: str) -> str:
    value = str(options.get(key, "")).strip()
    if not value:
        raise ValueError(f"The '{key}' option is required")
    return value


def build_environment(options: dict) -> dict[str, str]:
    secret = required(options, "control_secret")
    return {
        "TUNNEL_CONTROL_KEY_ID": required(options, "control_key_id"),
        "TUNNEL_CONTROL_SECRET_SHA256": hashlib.sha256(secret.encode("utf-8")).hexdigest(),
        "TAILSCALE_SOCKET": SOCKET,
        "TAILSCALE_HOSTNAME": required(options, "hostname"),
        "TAILSCALE_AUTH_KEY": required(options, "auth_key"),
        "TAILSCALE_SERVE_PORT": str(int(options.get("serve_port", 443))),
    }


def wait_for_socket(path: str, timeout: int = 15) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if Path(path).exists():
            return
        time.sleep(0.2)
    raise RuntimeError("tailscaled did not create its local socket")


def authenticate(environment: dict[str, str], auth_key_path: Path = AUTH_KEY_PATH) -> None:
    auth_key = environment.pop("TAILSCALE_AUTH_KEY")
    auth_key_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    auth_key_path.parent.chmod(0o700)
    descriptor = os.open(auth_key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(auth_key)
            handle.write("\n")
        auth_key_path.chmod(0o600)
        completed = subprocess.run(
            [
                "tailscale", "--socket", SOCKET, "up",
                "--auth-key", f"file:{auth_key_path}",
                "--hostname", environment["TAILSCALE_HOSTNAME"],
                "--accept-dns=false",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise TailscaleAuthenticationError(
                "Tailscale authentication failed; verify auth_key in the App Configuration tab"
            )
    finally:
        auth_key_path.unlink(missing_ok=True)


def main(options_path: Path = Path("/data/options.json")) -> None:
    options = json.loads(options_path.read_text(encoding="utf-8"))
    try:
        environment = build_environment(options)
    except (TypeError, ValueError) as exc:
        print("HA Fleet Tunnel cannot start: configuration is incomplete or invalid.", flush=True)
        print(f"Reason: {exc}", flush=True)
        print("Set auth_key and control_secret in the App Configuration tab, then start again.", flush=True)
        raise SystemExit(78) from None

    os.makedirs("/var/run/tailscale", exist_ok=True)
    tailscaled = subprocess.Popen(
        ["tailscaled", "--tun=userspace-networking", "--state=/data/tailscaled.state", f"--socket={SOCKET}"],
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    try:
        wait_for_socket(SOCKET)
        try:
            authenticate(environment)
        except TailscaleAuthenticationError as exc:
            print(f"HA Fleet Tunnel cannot authenticate: {exc}.", flush=True)
            raise SystemExit(78) from None
        relay = subprocess.Popen(
            ["socat", "TCP-LISTEN:8123,bind=127.0.0.1,fork,reuseaddr", "TCP:homeassistant:8123"],
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
        os.environ.update(environment)
        os.execv(sys.executable, [sys.executable, "-m", "app.main"])
    finally:
        tailscaled.terminate()


if __name__ == "__main__":
    main()
