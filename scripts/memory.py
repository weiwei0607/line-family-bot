"""
對話記憶模組
- 每個 LINE 群組維護獨立的滾動緩衝區（60 條）
- 對話訊息非同步寫入 Google Sheets「對話紀錄」tab（含 group_id 欄位）
- 機器人啟動時從 Sheets 還原各群組歷史
- 短暫記憶（機器人回覆）只存記憶體，TTL 2 小時後自動過濾
"""

import logging
import threading
from collections import deque, OrderedDict
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

TZ = ZoneInfo("Asia/Taipei")
_TAB = "對話紀錄"
_BUFFER_SIZE = 30
_CONTEXT_SIZE = 20
_MAX_MSG_LEN = 300
_EPHEMERAL_TTL_HOURS = 2
_SHEETS_MAX_ROWS = 500
_MAX_GROUPS = 20           # 限制同時存在的群組緩衝區數量

# 每個 group_id 一個獨立 deque，用 OrderedDict 實現 LRU 淘汰
_buffers: OrderedDict[str, deque] = OrderedDict()
_lock = threading.Lock()
_loaded = False

# 每個請求的 group_id context（thread-local）
_ctx = threading.local()


def set_context(group_id: str):
    """在請求最開始設定當前群組 ID。"""
    _ctx.group_id = group_id or "default"


def _gid() -> str:
    return getattr(_ctx, "group_id", "default")


def _buf(group_id: str) -> deque:
    with _lock:
        if group_id in _buffers:
            # 移到最後（最新使用）
            _buffers.move_to_end(group_id)
            return _buffers[group_id]
        # 淘汰最舊的群組如果超過上限
        while len(_buffers) >= _MAX_GROUPS:
            oldest_gid, _ = _buffers.popitem(last=False)
            logger.info("memory: evicted buffer for group %s", oldest_gid)
        _buffers[group_id] = deque(maxlen=_BUFFER_SIZE)
        return _buffers[group_id]


# ── 寫入 ──────────────────────────────────────────────────────────────────

def record(speaker: str, message: str):
    """記錄對話訊息到緩衝區，並非同步寫入 Sheets。"""
    gid = _gid()
    ts = datetime.now(TZ).isoformat()
    entry = {"ts": ts, "speaker": speaker, "message": message, "gid": gid}
    with _lock:
        _buf(gid).append(entry)
    from sheets import bg
    bg(_save_one, ts, speaker, message, gid)


def record_ephemeral(speaker: str, message: str):
    """短暫記憶：只存緩衝區，不寫 Sheets，TTL 後自動過濾。"""
    gid = _gid()
    ts = datetime.now(TZ).isoformat()
    entry = {"ts": ts, "speaker": speaker, "message": message,
             "gid": gid, "ephemeral": True}
    with _lock:
        _buf(gid).append(entry)


def _save_one(ts: str, speaker: str, message: str, gid: str):
    try:
        from sheets import _append, _ensure_tab
        _ensure_tab(_TAB)
        _append(_TAB, [ts, speaker, message[:_MAX_MSG_LEN], gid])
    except Exception as exc:
        logger.warning("memory._save_one failed: %s", exc)


# ── 讀取 ──────────────────────────────────────────────────────────────────

def get_recent(n: int = _CONTEXT_SIZE) -> list[dict]:
    gid = _gid()
    cutoff = datetime.now(TZ).timestamp() - _EPHEMERAL_TTL_HOURS * 3600
    with _lock:
        buf = list(_buf(gid))
    valid = [
        m for m in buf
        if not m.get("ephemeral")
        or datetime.fromisoformat(m["ts"]).timestamp() > cutoff
    ]
    return valid[-n:]


def format_for_ai(n: int = _CONTEXT_SIZE) -> str:
    """格式化最近 n 條訊息供 AI prompt 使用，含日期（跨日時顯示）。"""
    msgs = get_recent(n)
    if not msgs:
        return ""
    today = datetime.now(TZ).date().isoformat()
    lines = ["【最近對話紀錄】"]
    for m in msgs:
        ts = m["ts"]
        date_part = ts[:10]
        time_part = ts[11:16]
        label = time_part if date_part == today else f"{date_part[5:]} {time_part}"
        lines.append(f"[{label}] {m['speaker']}: {m['message']}")
    return "\n".join(lines)


# ── 啟動時還原 ────────────────────────────────────────────────────────────

def load_from_sheets(n: int = _BUFFER_SIZE):
    """從 Sheets 讀取最近記錄，按 group_id 分組填入各緩衝區（啟動時呼叫一次）。"""
    global _loaded
    if _loaded:
        return
    try:
        from sheets import _read, _ensure_tab
        _ensure_tab(_TAB)
        # 先讀取總行數，只抓最近 200 行（減少啟動時記憶體與 API 消耗）
        rows = _read(_TAB, "A2:D200")
        total = len(rows)
        if total >= _SHEETS_MAX_ROWS:
            _prune_sheets(rows)
            rows = rows[-_SHEETS_MAX_ROWS:]
        with _lock:
            for r in rows[-n:]:
                if len(r) < 3:
                    continue
                gid = r[3].strip() if len(r) >= 4 and r[3].strip() else "default"
                _buf(gid).append({
                    "ts":      r[0],
                    "speaker": r[1],
                    "message": r[2],
                    "gid":     gid,
                })
        _loaded = True
        logger.info("memory: loaded %d rows (total %d)", min(n, total), total)
    except Exception as exc:
        logger.warning("memory.load_from_sheets failed: %s", exc)


def _prune_sheets(all_rows: list):
    """把 Sheets 修剪到最新 _SHEETS_MAX_ROWS 行。只清除實際有資料的範圍，避免誤刪。"""
    try:
        from sheets import _get_service, _get_sheet_id
        keep = all_rows[-_SHEETS_MAX_ROWS:]
        svc = _get_service()
        sid = _get_sheet_id()
        total_rows = len(all_rows)
        # 只清除實際有資料的範圍（A2 開始）
        clear_range = f"{_TAB}!A2:D{total_rows + 1}"
        svc.spreadsheets().values().clear(
            spreadsheetId=sid, range=clear_range
        ).execute()
        if keep:
            svc.spreadsheets().values().update(
                spreadsheetId=sid,
                range=f"{_TAB}!A2",
                valueInputOption="USER_ENTERED",
                body={"values": keep},
            ).execute()
        logger.info("memory: pruned to %d rows", len(keep))
    except Exception as exc:
        logger.warning("memory._prune_sheets failed: %s", exc)
