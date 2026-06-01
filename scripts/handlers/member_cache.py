"""Member ID → name cache with thread-safe refresh."""

import logging
import threading
import time

logger = logging.getLogger(__name__)

_member_cache: dict[str, str] = {}
_cache_ts: float = 0
_member_lock = threading.Lock()


def _refresh_member_cache():
    try:
        from sheets import _read
        rows = _read("設定", "A2:B30")
        for r in rows:
            if len(r) >= 2 and r[0].strip() and r[1].strip():
                _member_cache[r[1].strip()] = r[0].strip()
    except Exception as _exc:
        logger.warning("Silent error: %s", _exc)


def resolve_member(user_id: str) -> str:
    global _cache_ts
    now = time.time()
    with _member_lock:
        if now - _cache_ts > 600:
            _refresh_member_cache()
            _cache_ts = now
        return _member_cache.get(user_id, "")


def set_member(user_id: str, name: str) -> None:
    with _member_lock:
        _member_cache[user_id] = name
