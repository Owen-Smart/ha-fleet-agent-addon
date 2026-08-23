# HA Fleet Tunnel

HA Fleet Tunnel 是 SITE 端的私人 Tailscale Serve 控制元件。它使用 userspace networking，不需要 `NET_ADMIN` 或 `/dev/net/tun`。

## 安全邊界

- Port `9090` 只在 HA App 內部網路監聽，`config.yaml` 不發布任何 host port。
- Fleet Agent 必須使用獨立 `control_key_id` 與 `control_secret` 進行 HMAC request signing。
- App 僅使用 Tailscale Serve，不啟用 Funnel。
- HA Web UI 經由容器內 `127.0.0.1:8123` relay 連到 Home Assistant；不直接發布 LAN 8123。

## 初次設定

- `hostname`：顯示在 Tailscale Admin Console 的 SITE 節點名稱。
- `auth_key`：Tailscale one-off auth key。完成首次加入後仍保存在 HA App 設定；PoC 完成後應改用更完整的金鑰生命週期。
- `control_key_id`、`control_secret`：只提供給同 SITE 的 Fleet Agent。

完成設定後啟動 App，先在 Tailscale Admin Console 確認節點，再由 Fleet Agent 呼叫 `/status`、`/enable` 與 `/disable`。

