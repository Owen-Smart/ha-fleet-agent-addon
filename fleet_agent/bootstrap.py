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


options = json.loads(Path("/data/options.json").read_text(encoding="utf-8"))
backend_url = required(options, "backend_url").rstrip("/")
verify_tls = bool(options.get("verify_tls", True))
parsed = urlparse(backend_url)
if parsed.scheme not in {"http", "https"} or not parsed.hostname:
    raise ValueError("backend_url must be a valid HTTP(S) URL")
if parsed.scheme != "https" and verify_tls:
    raise ValueError("Use an HTTPS backend, or explicitly disable verify_tls for an isolated evaluation LAN")

supervisor_token = os.environ.get("SUPERVISOR_TOKEN")
if not supervisor_token:
    raise RuntimeError("SUPERVISOR_TOKEN was not provided; homeassistant_api must be enabled")

environment = {
    "BACKEND_URL": backend_url,
    "SITE_CODE": required(options, "site_code"),
    "DEVICE_UID": required(options, "device_uid"),
    "AGENT_KEY_ID": required(options, "agent_key_id"),
    "AGENT_SECRET": required(options, "agent_secret"),
    "AGENT_VERSION": "0.1.0-ha-addon",
    "HEARTBEAT_SECONDS": str(options.get("heartbeat_seconds", 60)),
    "VERIFY_TLS": "true" if verify_tls else "false",
    "HA_URL": "http://supervisor/core",
    "HA_TOKEN": supervisor_token,
    "TUNNEL_STATUS": "not_configured",
    "ZIGBEE2MQTT_URL": str(options.get("zigbee2mqtt_url", "")),
    "ESPHOME_URL": str(options.get("esphome_url", "")),
}
os.environ.update(environment)
os.execv(sys.executable, [sys.executable, "-m", "app.main"])

