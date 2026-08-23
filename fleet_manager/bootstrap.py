import hashlib
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse


def required(item: dict, key: str) -> str:
    value = str(item.get(key, "")).strip()
    if not value:
        raise ValueError(f"The '{key}' option is required")
    return value


def validate_remote_url(value: object) -> str:
    remote_url = str(value or "").strip()
    if not remote_url:
        return ""
    parsed = urlparse(remote_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("remote_url must be empty or a valid HTTP(S) URL")
    return remote_url.rstrip("/")


def build_environment(options: dict) -> dict[str, str]:
    configured_sites = options.get("sites")
    if not isinstance(configured_sites, list) or not configured_sites:
        raise ValueError("At least one site must be configured")

    seen_site_codes: set[str] = set()
    seen_key_ids: set[str] = set()
    runtime_sites = []
    for item in configured_sites:
        if not isinstance(item, dict):
            raise ValueError("Each site entry must be an object")
        site_code = required(item, "site_code")
        key_id = required(item, "agent_key_id")
        if site_code in seen_site_codes:
            raise ValueError(f"Duplicate site_code: {site_code}")
        if key_id in seen_key_ids:
            raise ValueError(f"Duplicate agent_key_id: {key_id}")
        seen_site_codes.add(site_code)
        seen_key_ids.add(key_id)

        secret = required(item, "agent_secret")
        runtime_sites.append(
            {
                "site_code": site_code,
                "site_name": required(item, "site_name"),
                "device_uid": required(item, "device_uid"),
                "agent_key_id": key_id,
                "secret_sha256": hashlib.sha256(secret.encode("utf-8")).hexdigest(),
                "remote_url": validate_remote_url(item.get("remote_url")),
            }
        )

    offline_seconds = int(options.get("offline_seconds", 150))
    if not 30 <= offline_seconds <= 3600:
        raise ValueError("offline_seconds must be between 30 and 3600")
    return {
        "FLEET_MANAGER_SITES": json.dumps(runtime_sites, separators=(",", ":")),
        "FLEET_MANAGER_OFFLINE_SECONDS": str(offline_seconds),
    }


def main(options_path: Path = Path("/data/options.json")) -> None:
    options = json.loads(options_path.read_text(encoding="utf-8"))
    try:
        environment = build_environment(options)
    except (TypeError, ValueError) as exc:
        print("HA Fleet Manager cannot start: configuration is incomplete or invalid.", flush=True)
        print(f"Reason: {exc}", flush=True)
        print(
            "Open Settings > Apps > HA Fleet Manager > Configuration, configure at least one site and agent_secret, save, then start the app again.",
            flush=True,
        )
        raise SystemExit(78) from None
    os.environ.update(environment)
    os.execv(sys.executable, [sys.executable, "-m", "app.main"])


if __name__ == "__main__":
    main()


