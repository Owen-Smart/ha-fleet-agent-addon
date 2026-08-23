import asyncio
import json
import os
import random
from datetime import datetime, timezone

import httpx
import psutil

from .ha import HomeAssistantAdapter

BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000").rstrip("/")
AGENT_MODE = os.getenv("AGENT_MODE", "connected")
SITE_CODE = os.environ["SITE_CODE"]
DEVICE_UID = os.environ["DEVICE_UID"]
KEY_ID = os.environ["AGENT_KEY_ID"]
SECRET = os.environ["AGENT_SECRET"]
AGENT_VERSION = os.getenv("AGENT_VERSION", "0.1.0")
INTERVAL = int(os.getenv("HEARTBEAT_SECONDS", "60"))
VERIFY_TLS = os.getenv("VERIFY_TLS", "true").lower() not in {"0", "false", "no"}
HA = HomeAssistantAdapter(os.getenv("HA_URL", "http://homeassistant:8123"), os.getenv("HA_TOKEN"), VERIFY_TLS)


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
    headers = {"X-Agent-Key-Id": KEY_ID, "X-Agent-Secret": SECRET}
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
    response = await client.post(f"{BACKEND_URL}/api/agent/heartbeat", headers=headers, json=payload)
    response.raise_for_status()


async def run_evaluation(client: httpx.AsyncClient):
    while True:
        ha_status, version = await HA.health_and_version()
        print(
            json.dumps(
                {
                    "event": "evaluation_health",
                    "site_code": SITE_CODE,
                    "ha_status": ha_status,
                    "ha_version": version,
                    "agent_version": AGENT_VERSION,
                    "cpu_percent": psutil.cpu_percent(interval=0.1),
                    "ram_percent": psutil.virtual_memory().percent,
                    "disk_percent": psutil.disk_usage("/").percent,
                    "backend_reporting": "disabled_until_configured",
                },
                separators=(",", ":"),
            ),
            flush=True,
        )
        await asyncio.sleep(INTERVAL)


async def run_connected(client: httpx.AsyncClient):
    backoff = 2
    while True:
        try:
            headers = {"X-Agent-Key-Id": KEY_ID, "X-Agent-Secret": SECRET}
            response = await client.post(f"{BACKEND_URL}/api/agent/register", headers=headers)
            response.raise_for_status()
            await report(client)
            backoff = 2
            await asyncio.sleep(INTERVAL + random.uniform(0, min(5, INTERVAL / 10)))
        except (httpx.HTTPError, ValueError) as exc:
            print(f"agent connection failed: {exc}; retrying in {backoff}s", flush=True)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)


async def run():
    async with httpx.AsyncClient(timeout=10, verify=VERIFY_TLS) as client:
        if AGENT_MODE == "evaluation":
            print("HA Fleet Agent running in evaluation mode; outbound backend reporting is disabled", flush=True)
            await run_evaluation(client)
        else:
            await run_connected(client)


if __name__ == "__main__":
    asyncio.run(run())
