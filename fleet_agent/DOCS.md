# HA Fleet Agent

This app sends outbound health reports from Home Assistant OS to the central HA Fleet portal. It does not open a listening port and does not expose Home Assistant port 8123.

## Configuration

- `backend_url`: Public or LAN URL of the central backend, including `https://` and any nonstandard port.
- `site_code`, `device_uid`, `agent_key_id`: Identity provisioned by the backend.
- `agent_secret`: Unique site secret. It must match the backend's stored credential.
- `heartbeat_seconds`: Reporting interval; 60 seconds is recommended.
- `verify_tls`: Keep enabled. Disable only for an isolated evaluation LAN using a plain HTTP backend.
- `zigbee2mqtt_url`, `esphome_url`: Optional health URLs reachable from this app.
- `tunnel_url`: Fleet Tunnel 的 HA App 內部 URL；預設為本 Repository 的 Tunnel hostname。
- `tunnel_control_key_id`, `tunnel_control_secret`: Agent 呼叫 Tunnel API 的獨立 HMAC 憑證。
- `maintenance_ttl_seconds`: 遠端維修自動關閉秒數。Agent 將 lease 寫入 `/data`，Manager 中斷時仍會依期限關閉。

The app uses Home Assistant's internal Supervisor proxy and runtime `SUPERVISOR_TOKEN`; no HA long-lived access token is required.

The app intentionally refuses to start when `agent_secret` is empty. Its log will direct the operator to the Configuration tab instead of emitting a Python traceback or running without authentication.

The secret is not transmitted in an HTTP header. Each request is signed with HMAC-SHA256 over the method, path, timestamp, nonce, and request-body hash. The Manager rejects stale timestamps and reused nonces. This protects the evaluation API against credential disclosure and simple replay attacks, but HTTPS or a private Tailscale path is still required outside an isolated LAN.

The default boot mode is manual. Configure the backend and site credential first, start the app, verify a successful registration, and only then enable **Start on boot**. This prevents an unconfigured installation from entering a Supervisor watchdog restart loop.

## Example for an isolated LAN test

```yaml
backend_url: http://192.168.1.50:8080
site_code: SITE-001
device_uid: device-001
agent_key_id: agent-001
agent_secret: your-matching-site-secret
heartbeat_seconds: 60
verify_tls: false
zigbee2mqtt_url: ""
esphome_url: ""
```

Use HTTPS with certificate verification for any routed, shared, or Internet-accessible network.

## Metrics limitation

The current CPU, RAM, and disk readings describe the app container's available runtime view. They are adequate for connectivity demonstration but are not yet authoritative Home Assistant host metrics. A commercial build should obtain host data through approved Supervisor information endpoints and define exactly what each metric represents.

