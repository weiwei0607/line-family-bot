"""
對話記憶模組
- 在記憶體維護最近 60 條訊息的滾動緩衝區
- 每條訊息非同步存入 Google Sheets「對話紀錄」tab
- 機器人啟動時從 Sheets 讀取最近記錄還原緩衝區
"""

import logging
import threading
from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

TZ = ZoneInfo("Asia/Taipei")
_TAB = "對話紀錄"
_BUFFER_SIZE = 60
_CONTEXT_SIZE = 20   # 給 AI 的最近幾條
_MAX_MSG_LEN  = 300  # 存 Sheets 時截斷超長訊息

_buffer: deque = deque(maxlen=_BUFFER_SIZE)
_lock = threading.Lock()
_loaded = False


# ── 寫入 ──────────────────────────────────────────────────────────────────

def record(speaker: str, message: str):
    """記錄一條訊息到緩衝區，並非同步寫入 Sheets。"""
    ts = datetime.now(TZ).isoformat()
    entry = {"ts": ts, "speaker": speaker, "message": message}
    with _lock:
        _buffer.append(entry)
    from sheets import bg
    bg(_save_one, ts, speaker, message)


def _save_one(ts: str, speaker: str, message: str):
    try:
        from sheets import _append, _ensure_tab
        _ensure_tab(_TAB)
        _append(_TAB, [ts, speaker, message[:_MAX_MSG_LEN]])
    except Exception as exc:
        logger.warning("memory._save_one failed: %s", exc)


# ── 讀取 ──────────────────────────────────────────────────────────────────

def get_recent(n: int = _CONTEXT_SIZE) -> list[dict]:
    with _lock:
        return list(_buffer)[-n:]


def format_for_ai(n: int = _CONTEXT_SIZE) -> str:
    """格式化最近 n 條訊息，供 AI prompt 使用。"""
    msgs = get_recent(n)
    if not msgs:
        return ""
    lines = ["【最近對話紀錄】"]
    for m in msgs:
        ts_short = m["ts"][11:16]  # HH:MM
        lines.append(f"[{ts_short}] {m['speaker']}: {m['message']}")
    return "\n".join(lines)


# ── 啟動時還原 ────────────────────────────────────────────────────────────

def load_from_sheets(n: int = _BUFFER_SIZE):
    """從 Sheets 讀取最近 n 條記錄，填入緩衝區（只在啟動時呼叫一次）。"""
    global _loaded
    if _loaded:
        return
    try:
        from sheets import _read, _ensure_tab
        _ensure_tab(_TAB)
        rows = _read(_TAB, "A2:C3000")
        rows = rows[-n:]
        with _lock:
            _buffer.clear()
            for r in rows:
                if len(r) >= 3:
                    _buffer.append({"ts": r[0], "speaker": r[1], "message": r[2]})
        _loaded = True
        logger.info("memory: loaded %d rows from Sheets", len(rows))
    except Exception as exc:
        logger.warning("memory.load_from_sheets failed: %s", exc)
