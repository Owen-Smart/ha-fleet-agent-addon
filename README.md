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
- `agent_secret` 必須在安裝後，於 Home Assistant 的 App 設定頁個別輸入；空白時 Agent 會拒絕啟動並在日誌提示設定方式。
- 預設採手動啟動；完成後端與站點憑證設定、確認成功註冊後，再開啟「開機時啟動」，避免未設定完成時反覆重啟。
- HTTP 僅適合隔離的測試 LAN；正式環境必須使用 HTTPS。
- 完整的 Headscale 自動註冊與正式憑證輪替仍屬後續商業化工作。
