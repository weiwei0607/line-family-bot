# 家管助理 LINE 機器人 設定指南

## 第一步：申請 LINE Official Account

1. 前往 https://developers.line.biz
2. 建立一個新的 Provider（或用原有的）
3. 建立新的 **Messaging API Channel**，名稱如「家管助理」
4. 在 Channel 設定頁取得：
   - **Channel Secret**
   - **Channel Access Token**（Long-lived）

---

## 第二步：建立 Google Sheet

在 Google Sheets 建立一個新試算表，包含以下分頁：

### 📄 設定 Tab
| A（成員名字） | B（LINE User ID） |
|---|---|
| 爸爸 | Uxxxxxxx |
| 媽媽 | Uxxxxxxx |
| 我 | Uxxxxxxx |

> B 欄的 LINE User ID 要去 LINE Developers Console 找，
> 或在 webhook log 中看 `event.source.user_id`

### 📄 家事清單 Tab（A-F欄）
| 任務名稱 | 點數 | 分類 | 狀態 | 完成者 | 完成時間 |
|---|---|---|---|---|---|
| 洗碗 | 1 | 每日 | 待完成 | | |
| 打掃廚房 | 2 | 每週 | 待完成 | | |
| 倒垃圾 | 1 | 每週 | 待完成 | | |
| 洗衣服 | 2 | 每週 | 待完成 | | |

> 分類填「每週」的，每週一會自動重置

### 📄 點數記錄 Tab（A-E欄）
| 日期 | 成員 | 任務 | 點數 | 時間 |
|---|---|---|---|---|
（系統自動寫入）

### 📄 購物清單 Tab（A-F欄）
| 項目 | 加入者 | 加入時間 | 狀態 | 完成者 | 完成時間 |
|---|---|---|---|---|---|
（系統自動寫入）

### 📄 記帳 Tab（A-F欄）
| 日期 | 金額 | 分類 | 說明 | 記錄者 | 時間 |
|---|---|---|---|---|---|
（系統自動寫入）

---

## 第三步：部署到 Render

1. 把程式碼 push 到 GitHub（建新 repo：`line-family-bot`）
2. 到 Render.com → New Web Service → Connect GitHub repo
3. 設定環境變數：

| 變數名稱 | 說明 |
|---|---|
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE 機器人 token |
| `LINE_CHANNEL_SECRET` | LINE 機器人 secret |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID（和朋友群同一個）|
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret |
| `GOOGLE_REFRESH_TOKEN` | Google refresh token（同一個）|
| `FAMILY_SHEET_ID` | Google Sheet 的 ID（從網址取）|
| `GEMINI_API_KEY` | Gemini API key |
| `POINTS_THRESHOLD` | 每週點數目標（預設 5）|

4. Webhook URL 設為：`https://你的app.onrender.com/webhook`
5. 到 LINE Developers → Messaging API → Webhook URL 貼上

---

## 第四步：設定 GitHub Actions

在 GitHub repo 的 Settings → Secrets 新增：
- `FAMILY_LINE_CHANNEL_ACCESS_TOKEN`
- `FAMILY_LINE_GROUP_ID`（把機器人加入家庭群後，可從 webhook log 取得）
- `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REFRESH_TOKEN`
- `FAMILY_SHEET_ID`
- `GEMINI_API_KEY`

---

## 機器人指令速查

```
家事清單          → 看待完成家事
完成 [家事名稱]   → 標記完成並獲得點數
查點數            → 看本週大家的點數排行

買 [項目]         → 加入購物清單
買好了 [項目]     → 標記已購買
購物清單          → 查看購物清單

記帳 [金額] [說明]  → 記錄支出
查帳              → 查最近 7 天支出

@機器人 [問題]    → AI 問答
說明              → 顯示所有指令
```
