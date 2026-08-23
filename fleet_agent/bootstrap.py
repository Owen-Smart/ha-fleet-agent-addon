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
    evaluation_mode = bool(options.get("evaluation_mode", True))
    backend_url = str(options.get("backend_url", "")).strip().rstrip("/")
    agent_secret = str(options.get("agent_secret", "")).strip()
    verify_tls = bool(options.get("verify_tls", True))

    if not evaluation_mode:
        if not backend_url:
            raise ValueError("backend_url is required when evaluation_mode is disabled")
        parsed = urlparse(backend_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("backend_url must be a valid HTTP(S) URL")
        if parsed.scheme != "https" and verify_tls:
            raise ValueError("Use an HTTPS backend, or explicitly disable verify_tls for an isolated evaluation LAN")
        if not agent_secret:
            raise ValueError("agent_secret is required when evaluation_mode is disabled")

    supervisor_token = environ.get("SUPERVISOR_TOKEN")
    if not supervisor_token:
        raise RuntimeError("SUPERVISOR_TOKEN was not provided; homeassistant_api must be enabled")

    return {
        "AGENT_MODE": "evaluation" if evaluation_mode else "connected",
        "BACKEND_URL": backend_url,
        "SITE_CODE": required(options, "site_code"),
        "DEVICE_UID": required(options, "device_uid"),
        "AGENT_KEY_ID": required(options, "agent_key_id"),
        "AGENT_SECRET": agent_secret,
        "AGENT_VERSION": "0.1.2-ha-addon",
        "HEARTBEAT_SECONDS": str(options.get("heartbeat_seconds", 60)),
        "VERIFY_TLS": "true" if verify_tls else "false",
        "HA_URL": "http://supervisor/core",
        "HA_TOKEN": supervisor_token,
        "TUNNEL_STATUS": "not_configured",
        "ZIGBEE2MQTT_URL": str(options.get("zigbee2mqtt_url", "")),
        "ESPHOME_URL": str(options.get("esphome_url", "")),
    }


def main() -> None:
    options = json.loads(Path("/data/options.json").read_text(encoding="utf-8"))
    os.environ.update(build_environment(options, os.environ))
    os.execv(sys.executable, [sys.executable, "-m", "app.main"])


if __name__ == "__main__":
    main()
