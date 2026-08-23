import asyncio
import hashlib
import hmac
import json
import os
import random
import secrets
import time
from datetime import datetime, timezone

import httpx
import psutil

from .ha import HomeAssistantAdapter

BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000").rstrip("/")
SITE_CODE = os.environ["SITE_CODE"]
DEVICE_UID = os.environ["DEVICE_UID"]
KEY_ID = os.environ["AGENT_KEY_ID"]
SECRET = os.environ["AGENT_SECRET"]
AGENT_VERSION = os.getenv("AGENT_VERSION", "0.1.0")
INTERVAL = int(os.getenv("HEARTBEAT_SECONDS", "60"))
VERIFY_TLS = os.getenv("VERIFY_TLS", "true").lower() not in {"0", "false", "no"}
HA = HomeAssistantAdapter(os.getenv("HA_URL", "http://homeassistant:8123"), os.getenv("HA_TOKEN"), VERIFY_TLS)


def signed_headers(method: str, path: str, body: bytes = b"", timestamp: int | None = None, nonce: str | None = None) -> dict[str, str]:
    request_timestamp = str(timestamp if timestamp is not None else int(time.time()))
    request_nonce = nonce or secrets.token_urlsafe(24)
    body_sha256 = hashlib.sha256(body).hexdigest()
    canonical = "\n".join((method.upper(), path, request_timestamp, request_nonce, body_sha256)).encode("utf-8")
    signing_key = hashlib.sha256(SECRET.encode("utf-8")).digest()
    signature = hmac.new(signing_key, canonical, hashlib.sha256).hexdigest()
    return {
        "X-Agent-Key-Id": KEY_ID,
        "X-Agent-Timestamp": request_timestamp,
        "X-Agent-Nonce": request_nonce,
        "X-Agent-Signature": signature,
    }


async def service_status(client: httpx.AsyncClient, url: str | None) -> str:
    if not url:
        return "not_configured"
    try:
        response = await client.get(url, timeout=3)
        return "available" if response.status_code < 500 else "unavailable"
    except httpx.HTTPError:
        return "unavailable"


async def report(client: httpx.AsyncClient):
    ha_status, version = await HA.health_and_version()
    payload = {
        "site_code": SITE_CODE,
        "device_uid": DEVICE_UID,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "ha_version": version or f"unknown ({ha_status})",
        "agent_version": AGENT_VERSION,
        "cpu_percent": psutil.cpu_percent(interval=0.1),
        "ram_percent": psutil.virtual_memory().percent,
        "disk_percent": psutil.disk_usage("/").percent,
        "tunnel_status": os.getenv("TUNNEL_STATUS", "not_configured"),
        "zigbee2mqtt_status": await service_status(client, os.getenv("ZIGBEE2MQTT_URL")),
        "esphome_status": await service_status(client, os.getenv("ESPHOME_URL")),
    }
    path = "/api/agent/heartbeat"
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    headers = {**signed_headers("POST", path, body), "Content-Type": "application/json"}
    response = await client.post(f"{BACKEND_URL}{path}", headers=headers, content=body)
    response.raise_for_status()


async def run():
    backoff = 2
    async with httpx.AsyncClient(timeout=10, verify=VERIFY_TLS) as client:
        while True:
            try:
                path = "/api/agent/register"
                response = await client.post(f"{BACKEND_URL}{path}", headers=signed_headers("POST", path))
                response.raise_for_status()
                await report(client)
                backoff = 2
                await asyncio.sleep(INTERVAL + random.uniform(0, min(5, INTERVAL / 10)))
            except (httpx.HTTPError, ValueError) as exc:
                print(f"agent connection failed: {exc}; retrying in {backoff}s", flush=True)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)


if __name__ == "__main__":
    asyncio.run(run())

