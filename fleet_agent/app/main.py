import asyncio
import hashlib
import hmac
import json
import os
import random
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
TUNNEL_URL = os.getenv("TUNNEL_URL", "").rstrip("/")
TUNNEL_KEY_ID = os.getenv("TUNNEL_CONTROL_KEY_ID", "")
TUNNEL_SECRET = os.getenv("TUNNEL_CONTROL_SECRET", "")
DEFAULT_MAINTENANCE_TTL = int(os.getenv("MAINTENANCE_TTL_SECONDS", "3600"))
LEASE_PATH = Path(os.getenv("MAINTENANCE_LEASE_PATH", "/data/maintenance_lease.json"))


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


def tunnel_headers(method: str, path: str, body: bytes = b"") -> dict[str, str]:
    timestamp = str(int(time.time()))
    nonce = secrets.token_urlsafe(24)
    body_sha256 = hashlib.sha256(body).hexdigest()
    canonical = "\n".join((method.upper(), path, timestamp, nonce, body_sha256)).encode("utf-8")
    key = hashlib.sha256(TUNNEL_SECRET.encode("utf-8")).digest()
    return {
        "X-Tunnel-Key-Id": TUNNEL_KEY_ID,
        "X-Tunnel-Timestamp": timestamp,
        "X-Tunnel-Nonce": nonce,
        "X-Tunnel-Signature": hmac.new(key, canonical, hashlib.sha256).hexdigest(),
    }


def tunnel_configured() -> bool:
    return bool(TUNNEL_URL and TUNNEL_KEY_ID and TUNNEL_SECRET)


async def tunnel_call(client: httpx.AsyncClient, method: str, path: str) -> dict:
    if not tunnel_configured():
        raise RuntimeError("Fleet Tunnel is not configured")
    response = await client.request(method, f"{TUNNEL_URL}{path}", headers=tunnel_headers(method, path), timeout=15)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Fleet Tunnel returned an invalid response")
    return payload


def write_lease(command_id: str, expires_at: datetime) -> None:
    LEASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = LEASE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps({"command_id": command_id, "expires_at": expires_at.isoformat()}), encoding="utf-8")
    temporary.replace(LEASE_PATH)


def clear_lease() -> None:
    LEASE_PATH.unlink(missing_ok=True)


def read_lease_expiry() -> datetime | None:
    try:
        value = json.loads(LEASE_PATH.read_text(encoding="utf-8"))["expires_at"]
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


async def enforce_lease(client: httpx.AsyncClient) -> None:
    expiry = read_lease_expiry()
    if expiry and datetime.now(timezone.utc) >= expiry:
        await tunnel_call(client, "POST", "/disable")
        clear_lease()


async def tunnel_snapshot(client: httpx.AsyncClient) -> dict[str, str]:
    if not tunnel_configured():
        return {"status": "not_configured", "remote_url": ""}
    try:
        result = await tunnel_call(client, "GET", "/status")
        return {"status": str(result.get("status", "ERROR")), "remote_url": str(result.get("remote_url", ""))}
    except (httpx.HTTPError, RuntimeError, ValueError):
        return {"status": "ERROR", "remote_url": ""}


async def execute_command(client: httpx.AsyncClient, command: dict, seen: set[str]) -> dict:
    command_id = str(command.get("id", ""))
    action = str(command.get("action", ""))
    if not command_id or command_id in seen:
        raise ValueError("Command is missing an id or has already been processed")
    expires_at = datetime.fromisoformat(str(command.get("expires_at", "")))
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) >= expires_at:
        raise ValueError("Command has expired")
    if action not in {"enable", "disable"}:
        raise ValueError("Command action is not allowed")
    seen.add(command_id)
    result = await tunnel_call(client, "POST", f"/{action}")
    if action == "enable":
        ttl = max(300, min(int(command.get("ttl_seconds", DEFAULT_MAINTENANCE_TTL)), 86400))
        write_lease(command_id, datetime.now(timezone.utc) + timedelta(seconds=ttl))
    else:
        clear_lease()
    return {"id": command_id, "success": True, "status": result.get("status"), "remote_url": result.get("remote_url", "")}


async def service_status(client: httpx.AsyncClient, url: str | None) -> str:
    if not url:
        return "not_configured"
    try:
        response = await client.get(url, timeout=3)
        return "available" if response.status_code < 500 else "unavailable"
    except httpx.HTTPError:
        return "unavailable"


async def report(client: httpx.AsyncClient, command_result: dict | None = None) -> dict:
    ha_status, version = await HA.health_and_version()
    tunnel = await tunnel_snapshot(client)
    payload = {
        "site_code": SITE_CODE,
        "device_uid": DEVICE_UID,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "ha_version": version or f"unknown ({ha_status})",
        "agent_version": AGENT_VERSION,
        "cpu_percent": psutil.cpu_percent(interval=0.1),
        "ram_percent": psutil.virtual_memory().percent,
        "disk_percent": psutil.disk_usage("/").percent,
        "tunnel_status": tunnel["status"],
        "remote_url": tunnel["remote_url"],
        "zigbee2mqtt_status": await service_status(client, os.getenv("ZIGBEE2MQTT_URL")),
        "esphome_status": await service_status(client, os.getenv("ESPHOME_URL")),
    }
    if command_result:
        payload["command_result"] = command_result
    path = "/api/agent/heartbeat"
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    headers = {**signed_headers("POST", path, body), "Content-Type": "application/json"}
    response = await client.post(f"{BACKEND_URL}{path}", headers=headers, content=body)
    response.raise_for_status()
    result = response.json()
    return result if isinstance(result, dict) else {}


async def run():
    backoff = 2
    seen_commands: set[str] = set()
    command_result: dict | None = None
    async with httpx.AsyncClient(timeout=10, verify=VERIFY_TLS) as client:
        while True:
            try:
                await enforce_lease(client)
                path = "/api/agent/register"
                response = await client.post(f"{BACKEND_URL}{path}", headers=signed_headers("POST", path))
                response.raise_for_status()
                response_payload = await report(client, command_result)
                command_result = None
                command = response_payload.get("command")
                if isinstance(command, dict):
                    try:
                        command_result = await execute_command(client, command, seen_commands)
                    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
                        command_result = {"id": str(command.get("id", "")), "success": False, "error": str(exc)}
                    await report(client, command_result)
                    command_result = None
                backoff = 2
                await asyncio.sleep(INTERVAL + random.uniform(0, min(5, INTERVAL / 10)))
            except (httpx.HTTPError, ValueError) as exc:
                print(f"agent connection failed: {exc}; retrying in {backoff}s", flush=True)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)


if __name__ == "__main__":
    asyncio.run(run())

