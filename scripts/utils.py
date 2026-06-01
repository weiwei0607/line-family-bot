"""
LINE Family Bot — Shared utilities.
"""

import os
import time
import threading
import requests

# ─── Telegram Alert ───────────────────────────────────────

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
    except Exception as exc:
        import logging
        logging.warning("send_telegram_alert: %s", exc)


# ─── Rate Limiting ────────────────────────────────────────

_rate_limit_lock = threading.Lock()
_rate_limit_buckets: dict[str, tuple[int, float]] = {}  # user_id -> (count, window_start)


def rate_limit_check(user_id: str, max_requests: int = 30, window_seconds: int = 60) -> bool:
    """Return True if user is allowed, False if rate-limited."""
    if not user_id:
        return True
    now = time.time()
    with _rate_limit_lock:
        count, window_start = _rate_limit_buckets.get(user_id, (0, now))
        if now - window_start > window_seconds:
            _rate_limit_buckets[user_id] = (1, now)
            return True
        if count >= max_requests:
            return False
        _rate_limit_buckets[user_id] = (count + 1, window_start)
        return True
