# 🏠 家管助理 LINE 機器人

> 一個部署在 Render 上的 LINE 群組機器人，幫助家庭成員管理家事、記帳、購物與日常互動。整合 Google Sheets、Gemini AI、edge-tts 語音與多種生活 API。

---

## ✨ 功能一覽

### 家庭管理
| 功能 | 說明 |
|------|------|
| 🧹 **家事系統** | 每週自動重置家事清單，完成獲得點數，週日結算排行榜 |
| 🛒 **購物清單** | 群組協作購物，標記已買項目 |
| 💰 **記帳系統** | 快速記錄支出，查詢近期消費明細 |
| 📊 **Google Sheets 同步** | 所有資料即時寫入雲端試算表 |

### 娛樂與生活
| 功能 | 說明 |
|------|------|
| 🔊 **AI 語音** | `說 [文字]` 將文字轉為自然語音（edge-tts + MPEG 轉碼） |
| 🤖 **AI 問答** | `@機器人 [問題]` 呼叫 Gemini 回答任何問題 |
| 🌤️ **天氣查詢** | 支援台灣與國際城市，含未來預報 |
| 💱 **匯率查詢** | 即時台幣對各國貨幣匯率 |
| 🎲 **趣味功能** | 抽籤、猜拳、搖骰子、配對星座 |

---

## 🏗️ 技術架構

```
使用者訊息
    ↓
LINE Webhook → Render (Flask + Gunicorn)
    ↓
┌─────────────┬─────────────┬─────────────┬─────────────┐
│ 指令分發器   │   AI 模組    │  外部 API   │ Google API  │
│ commands.py  │  gemini.py   │  weather.py │  sheets.py  │
└─────────────┴─────────────┴─────────────┴─────────────┘
    ↓
SQLite (本地狀態)  +  Google Sheets (持久化)
```

| 層級 | 技術 |
|------|------|
| **後端** | Python 3.11, Flask, Gunicorn (1 worker) |
| **LINE SDK** | line-bot-sdk v3 |
| **AI** | Gemini 2.5 Flash (Google GenAI) |
| **語音** | edge-tts + imageio-ffmpeg (MPEG-2 → MPEG-1 轉碼) |
| **資料庫** | SQLite (群組狀態) + Google Sheets (家事/記帳) |
| **排程** | APScheduler (每日/每週任務) |
| **部署** | Render Web Service (自動部署) |

---

## 🔧 核心技術挑戰

### 1. TTS 語音格式兼容性
**問題**：edge-tts 輸出 MPEG-2 Layer III 24kHz，LINE 伺服器無法正確解析透過 `push_message` 發送的語音檔。

**解法**：
- 使用 `imageio-ffmpeg` 將音訊轉碼為 MPEG-1 Layer III 44.1kHz 標準 MP3
- 經過多次迭代發現 `push_message` 發送 `AudioMessage` 有隱性限制，最終改用 `reply_message` (`reply_audio`) 回覆語音，與 LINE 官方行為一致
- 加入 Catbox 匿名上傳作為 fallback，繞過 Cloudflare 對 Render URL 的阻擋

### 2. 非同步架構避免 Webhook 超時
**問題**：AI 生成與語音合成耗時 2-5 秒，超過 LINE webhook 3 秒 timeout。

**解法**：
- 採用「秒回文字 + 背景 thread 推送結果」的雙階段模式
- Telegram alert 作為監控與診斷通道，即時追蹤 TTS 生成狀態

### 3. Google Sheets 作為無伺服器資料庫
**問題**：家庭成員需要共用資料，但不想維護 PostgreSQL。

**解法**：
- 以 Google Sheets 作為「雲端資料庫」，透過 Google API 讀寫
- 每週一排程自動重置「每週」分類家事
- 點數閾值可透過環境變數 `POINTS_THRESHOLD` 調整

---

## 🚀 部署方式

### 環境變數

| 變數 | 說明 | 必填 |
|------|------|------|
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Messaging API long-lived token | ✅ |
| `LINE_CHANNEL_SECRET` | LINE Channel Secret | ✅ |
| `LINE_GROUP_ID` | 家庭群組 ID（用於排程推播） | ✅ |
| `GOOGLE_CLIENT_ID` | Google OAuth Client ID | ✅ |
| `GOOGLE_CLIENT_SECRET` | Google OAuth Client Secret | ✅ |
| `GOOGLE_REFRESH_TOKEN` | Google OAuth refresh token | ✅ |
| `FAMILY_SHEET_ID` | Google Sheets ID | ✅ |
| `GEMINI_API_KEY` | Google Gemini API key | ✅ |
| `RENDER_EXTERNAL_URL` | Render 部署網址（用於 TTS 音檔 URL） | ✅ |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token（監控用） | ❌ |
| `TELEGRAM_CHAT_ID` | Telegram chat ID（監控用） | ❌ |
| `POINTS_THRESHOLD` | 每週點數目標（預設 5） | ❌ |

### 步驟
1. Fork / clone 本專案
2. 在 Render 建立 Web Service，連接 GitHub repo
3. 設定上述環境變數
4. 在 LINE Developers Console 設定 Webhook URL：`https://<your-app>.onrender.com/webhook`
5. （選用）設定 GitHub Actions 排程推播

---

## 📁 專案結構

```
line-family-bot/
├── app.py                  # Flask 入口與 webhook 路由
├── requirements.txt        # Python 依賴
├── render.yaml             # Render 部署設定
├── scripts/
│   ├── commands.py         # 指令分發與邏輯（50+ 指令）
│   ├── api_helpers.py      # 外部 API 整合（天氣、匯率、翻譯等）
│   ├── weather.py          # 天氣查詢（Open-Meteo + wttr.in）
│   ├── line_push.py        # LINE push/reply 封裝
│   ├── tts_store.py        # TTS 音檔 SQLite 持久化
│   └── webhook.py          # webhook 處理與驗證
├── shared/
│   ├── alerts.py           # Telegram 監控告警
│   └── google_sheets.py    # Google Sheets 讀寫
└── data/                   # SQLite 資料庫
```

---

## 📝 指令速查

```
家事清單                → 查看本週待完成家事
完成 [家事名稱]         → 標記完成並獲得點數
查點數                  → 本週點數排行榜

買 [項目]               → 加入購物清單
買好了 [項目]           → 標記已購買
購物清單                → 查看購物清單

記帳 [金額] [說明]      → 記錄支出
查帳                    → 最近 7 天支出明細

說 [文字]               → AI 語音朗讀
@機器人 [問題]          → Gemini AI 問答

天氣 [城市]             → 即時天氣與預報
匯率                    → 台幣對主要貨幣
說明                    → 顯示完整指令清單
```

---

## 📄 License

MIT License — 歡迎參考與改作。
