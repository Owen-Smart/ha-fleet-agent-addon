# HA Fleet Agent for Home Assistant

這是一個獨立的 Home Assistant App／Add-on Repository，提供 HA Fleet Agent。

Fleet Agent 會從 Home Assistant 主動向中央 Fleet 平台回報健康狀態，不會開放 HA 8123，也不需要手動建立 Home Assistant Long-Lived Access Token。

## 安裝

在 Home Assistant 開啟：

**設定 → 應用程式 → 應用程式商店 → 右上角選單 → 儲存庫**

加入：

```text
https://github.com/Owen-Smart/ha-fleet-agent-addon
```

完成後即可在應用程式商店安裝 **HA Fleet Agent**。

## 注意

- Repository 不包含任何實際密碼、Token 或站點憑證。
- 尚未部署中央平台時保留 `evaluation_mode: true`；Agent 會持續驗證本機 HA 健康狀態，但不會向外傳送資料。
- 要啟用中央回報時，先配置獨立的 `agent_secret` 與 `backend_url`，再將 `evaluation_mode` 改為 `false`。
- HTTP 僅適合隔離的測試 LAN；正式環境必須使用 HTTPS。
- 完整的 Headscale 自動註冊與正式憑證輪替仍屬後續商業化工作。
