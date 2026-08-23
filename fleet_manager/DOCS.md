# HA Fleet Manager

HA Fleet Manager 是第一版的輕量遠端使用與維修入口，安裝於 Owen HA。

## 第一版範圍

- 接收已授權 Fleet Agent 的即時狀態。
- 在 Home Assistant 側邊欄顯示 SITE 是否在線。
- 顯示目前 HA／Agent 版本與資源使用狀況。
- 在設定 Tunnel URL 後開啟遠端 Home Assistant。
- 不保存歷史狀態，不使用 PostgreSQL 或 SQLite。

## 安全限制

- Manager UI 僅透過 Home Assistant Ingress 提供。
- Port `8099` 只提供 Agent 註冊與狀態回報 API，不提供 Manager UI。
- 每個 SITE 必須使用不同的 `agent_key_id` 與高強度 `agent_secret`。
- 第一版的 Agent API 僅適合隔離的測試區網。跨網路使用前必須透過加密 Tunnel 或 HTTPS。
- 不得將 Home Assistant `8123`、MCP、Supervisor 或 Port `8099`直接公開至 Internet。

## Owen HA 設定

至少設定一個 SITE，並讓 SITE 設定與 Agent 完全一致：

- `site_code`
- `device_uid`
- `agent_key_id`
- `agent_secret`

`remote_url` 可以先留空；完成 Tunnel Client 後再填入該 SITE 的私人 HTTPS URL。


