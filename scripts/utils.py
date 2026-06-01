"""
LINE Family Bot — Shared utilities.
"""

import os
import requests


def send_telegram_alert(msg: str) -> None:
    """發送 Telegram 告警給管理員"""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not bot_token or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            data={"chat_id": chat_id, "text": f"🏠 家管助理 Alert\n\n{msg}"[:4000]},
            timeout=10,
        )
    except Exception:
        pass
