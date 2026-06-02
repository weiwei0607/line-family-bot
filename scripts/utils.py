"""
LINE Family Bot — Shared utilities.
"""

import time
import threading

from shared.alerts import send_telegram_alert as _send_telegram_alert_raw


def send_telegram_alert(msg: str) -> None:
    """發送 Telegram 告警給管理員"""
    return _send_telegram_alert_raw(msg, prefix="🏠 家管助理 Alert")


# ─── Rate Limiting ────────────────────────────────────────

_rate_limit_lock = threading.Lock()
_rate_limit_buckets: dict[str, tuple[int, float]] = {}  # user_id -> (count, window_start)


def rate_limit_check(user_id: str, max_requests: int = 30, window_seconds: int = 60) -> bool:
    """Return True if user is allowed, False if rate-limited."""
    if not user_id:
        return True
    now = time.time()
    with _rate_limit_lock:
        # Evict stale entries every ~100 calls to prevent unbounded growth
        if len(_rate_limit_buckets) > 200:
            stale = [k for k, (_, ws) in _rate_limit_buckets.items()
                     if now - ws > window_seconds * 2]
            for k in stale:
                del _rate_limit_buckets[k]

        count, window_start = _rate_limit_buckets.get(user_id, (0, now))
        if now - window_start > window_seconds:
            _rate_limit_buckets[user_id] = (1, now)
            return True
        if count >= max_requests:
            return False
        _rate_limit_buckets[user_id] = (count + 1, window_start)
        return True
