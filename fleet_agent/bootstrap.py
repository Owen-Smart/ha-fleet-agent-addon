import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse


def required(options: dict, key: str) -> str:
    value = str(options.get(key, "")).strip()
    if not value:
        raise ValueError(f"The '{key}' option is required")
    return value


def build_environment(options: dict, environ: dict[str, str]) -> dict[str, str]:
    backend_url = required(options, "backend_url").rstrip("/")
    agent_secret = required(options, "agent_secret")
    verify_tls = bool(options.get("verify_tls", True))

    parsed = urlparse(backend_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("backend_url must be a valid HTTP(S) URL")
    if parsed.scheme != "https" and verify_tls:
        raise ValueError("Use an HTTPS backend, or explicitly disable verify_tls for an isolated evaluation LAN")

    supervisor_token = environ.get("SUPERVISOR_TOKEN")
    if not supervisor_token:
        raise RuntimeError("SUPERVISOR_TOKEN was not provided; homeassistant_api must be enabled")

    return {
        "BACKEND_URL": backend_url,
        "SITE_CODE": required(options, "site_code"),
        "DEVICE_UID": required(options, "device_uid"),
        "AGENT_KEY_ID": required(options, "agent_key_id"),
        "AGENT_SECRET": agent_secret,
        "AGENT_VERSION": "0.1.5-ha-addon",
        "HEARTBEAT_SECONDS": str(options.get("heartbeat_seconds", 60)),
        "VERIFY_TLS": "true" if verify_tls else "false",
        "HA_URL": "http://supervisor/core",
        "HA_TOKEN": supervisor_token,
        "TUNNEL_STATUS": "not_configured",
        "ZIGBEE2MQTT_URL": str(options.get("zigbee2mqtt_url", "")),
        "ESPHOME_URL": str(options.get("esphome_url", "")),
        "TUNNEL_URL": str(options.get("tunnel_url", "")).rstrip("/"),
        "TUNNEL_CONTROL_KEY_ID": str(options.get("tunnel_control_key_id", "")).strip(),
        "TUNNEL_CONTROL_SECRET": str(options.get("tunnel_control_secret", "")).strip(),
        "MAINTENANCE_TTL_SECONDS": str(options.get("maintenance_ttl_seconds", 3600)),
        "MAINTENANCE_LEASE_PATH": "/data/maintenance_lease.json",
    }


def main(options_path: Path = Path("/data/options.json")) -> None:
    options = json.loads(options_path.read_text(encoding="utf-8"))
    try:
        environment = build_environment(options, os.environ)
    except (ValueError, RuntimeError) as exc:
        print("HA Fleet Agent cannot start: configuration is incomplete or invalid.", flush=True)
        print(f"Reason: {exc}", flush=True)
        print(
            "Open Settings > Apps > HA Fleet Agent > Configuration, set backend_url and agent_secret, save, then start the app again.",
            flush=True,
        )
        raise SystemExit(78) from None
    os.environ.update(environment)
    os.execv(sys.executable, [sys.executable, "-m", "app.main"])


if __name__ == "__main__":
    main()
