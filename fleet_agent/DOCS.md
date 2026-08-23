# HA Fleet Agent

This app sends outbound health reports from Home Assistant OS to the central HA Fleet portal. It does not open a listening port and does not expose Home Assistant port 8123.

## Configuration

- `evaluation_mode`: Enabled by default. The app verifies local Home Assistant health and stays running without sending data to a backend.
- `backend_url`: Public or LAN URL of the central backend, including `https://` and any nonstandard port. Required when evaluation mode is disabled.
- `site_code`, `device_uid`, `agent_key_id`: Identity provisioned by the backend.
- `agent_secret`: Unique site secret. It must match the backend's stored credential and is required when evaluation mode is disabled.
- `heartbeat_seconds`: Reporting interval; 60 seconds is recommended.
- `verify_tls`: Keep enabled. Disable only for an isolated evaluation LAN using a plain HTTP backend.
- `zigbee2mqtt_url`, `esphome_url`: Optional health URLs reachable from this app.

The app uses Home Assistant's internal Supervisor proxy and runtime `SUPERVISOR_TOKEN`; no HA long-lived access token is required.

Leave `evaluation_mode` enabled until the central Fleet backend and a unique site credential have been provisioned. Evaluation mode performs no outbound backend requests and writes a structured local health event to the app log every reporting interval.

## Example for an isolated LAN test

```yaml
evaluation_mode: false
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
