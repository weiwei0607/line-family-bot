#!/usr/bin/env python3
"""
Log Render memory usage to Google Sheets and send Telegram alert if high.
Runs from GitHub Actions on schedule.
"""
import logging
import os
import sys
from datetime import datetime, timezone, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

TW_TZ = timezone(timedelta(hours=8))
DEFAULT_TAB = "記憶體監控"


def fetch_memory(url: str) -> dict:
    import requests
    r = requests.get(f"{url}/memory", timeout=15)
    r.raise_for_status()
    return r.json()


def send_telegram_alert(msg: str) -> None:
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not bot_token or not chat_id:
        return
    import requests
    try:
        requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            data={"chat_id": chat_id, "text": f"🚨 家管助理記憶體告警\n\n{msg}"[:4000]},
            timeout=10,
        )
    except Exception as exc:
        logger.warning("Telegram alert failed: %s", exc)


def get_sheets_service():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials(
        None,
        refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
    )
    return build("sheets", "v4", credentials=creds)


def _tab_exists(service, sheet_id: str, title: str) -> bool:
    try:
        service.spreadsheets().get(spreadsheetId=sheet_id, ranges=[title]).execute()
        return True
    except Exception:
        return False


def ensure_tab(service, sheet_id: str, title: str) -> None:
    if _tab_exists(service, sheet_id, title):
        return
    body = {
        "requests": [
            {
                "addSheet": {
                    "properties": {
                        "title": title,
                        "gridProperties": {"rowCount": 5000, "columnCount": 10},
                    }
                }
            }
        ]
    }
    service.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body=body).execute()
    service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=f"{title}!A1:C1",
        valueInputOption="USER_ENTERED",
        body={"values": [["時間", "RSS MB", "虛擬記憶體 MB"]]},
    ).execute()


def append_log(service, sheet_id: str, title: str, ts: str, rss, vmem) -> None:
    values = [[ts, rss, vmem]]
    service.spreadsheets().values().append(
        spreadsheetId=sheet_id,
        range=f"{title}!A:C",
        valueInputOption="USER_ENTERED",
        body={"values": values},
        insertDataOption="INSERT_ROWS",
    ).execute()


def main() -> int:
    url = os.environ.get("RENDER_EXTERNAL_URL", "https://line-family-bot-ump0.onrender.com").rstrip("/")
    sheet_id = os.environ.get("FAMILY_SHEET_ID", "")
    threshold = float(os.environ.get("MEMORY_ALERT_THRESHOLD_MB", "400"))

    if not sheet_id:
        logger.error("FAMILY_SHEET_ID not set")
        return 1

    try:
        data = fetch_memory(url)
    except Exception as exc:
        logger.error("Failed to fetch /memory from %s: %s", url, exc)
        return 1

    rss = data.get("rss_mb")
    vmem = data.get("vmem_mb")
    ts = datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M:%S")
    logger.info("Memory at %s — RSS: %s MB, VMEM: %s MB", ts, rss, vmem)

    try:
        service = get_sheets_service()
        ensure_tab(service, sheet_id, DEFAULT_TAB)
        append_log(service, sheet_id, DEFAULT_TAB, ts, rss, vmem)
        logger.info("Logged to Sheet tab '%s'", DEFAULT_TAB)
    except Exception as exc:
        logger.error("Failed to write Sheet: %s", exc)

    if rss and rss > threshold:
        send_telegram_alert(
            f"Render 記憶體超過 {threshold}MB！\n\n"
            f"時間：{ts}\n"
            f"RSS：{rss} MB\n"
            f"VMEM：{vmem} MB\n\n"
            f"建議檢查 Render Dashboard 或重啟服務。"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
