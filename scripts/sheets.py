"""
Google Sheets helper — 家庭群機器人資料層
Tabs: 家事清單, 點數記錄, 購物清單, 記帳, 設定
"""

from __future__ import annotations

import os
import json
import time
import threading
from datetime import datetime, timezone, timedelta
import logging
from google.oauth2.credentials import Credentials

logger = logging.getLogger(__name__)

# ── 簡易快取（避免每個指令都打 Sheets API）──────
_sheet_cache: dict[str, tuple] = {}  # key -> (value, timestamp)
_SHEET_CACHE_MAX = 100

def _sc_get(key: str, ttl: int):
    entry = _sheet_cache.get(key)
    if entry and time.time() - entry[1] < ttl:
        return entry[0]
    return None

def _sc_set(key: str, value):
    _sheet_cache[key] = (value, time.time())
    if len(_sheet_cache) > _SHEET_CACHE_MAX:
        _sheet_cache.pop(next(iter(_sheet_cache)))

def _sc_del(*keys):
    for k in keys:
        _sheet_cache.pop(k, None)
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

TW_TZ = timezone(timedelta(hours=8))

def _now_str():
    return datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M")

def _today_str():
    return datetime.now(TW_TZ).strftime("%Y-%m-%d")

def _week_start():
    d = datetime.now(TW_TZ).date()
    return (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")

_SHEETS_SERVICE = None

def _get_service():
    global _SHEETS_SERVICE
    if _SHEETS_SERVICE is not None:
        return _SHEETS_SERVICE
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")
    if creds_json:
        info = json.loads(creds_json)
    else:
        info = {
            "client_id": os.environ.get("GOOGLE_CLIENT_ID", ""),
            "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET", ""),
            "refresh_token": os.environ.get("GOOGLE_REFRESH_TOKEN", ""),
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    creds = Credentials(
        token=None,
        refresh_token=info["refresh_token"],
        token_uri=info["token_uri"],
        client_id=info["client_id"],
        client_secret=info["client_secret"],
    )
    _SHEETS_SERVICE = build("sheets", "v4", credentials=creds, cache_discovery=False)
    return _SHEETS_SERVICE

def _get_sheet_id():
    return os.environ["FAMILY_SHEET_ID"]

def _ensure_tab(tab_name: str) -> bool:
    """Auto-create a sheet tab if it doesn't exist."""
    try:
        svc = _get_service()
        sid = _get_sheet_id()
        meta = svc.spreadsheets().get(spreadsheetId=sid).execute()
        titles = [s["properties"]["title"] for s in meta.get("sheets", [])]
        if tab_name in titles:
            return True
        svc.spreadsheets().batchUpdate(
            spreadsheetId=sid,
            body={"requests": [{"addSheet": {"properties": {"title": tab_name}}}]},
        ).execute()
        return True
    except Exception as e:
        logger.warning("ensure_tab %s failed: %s", tab_name, e)
        return False


def _retry_gapi(fn, max_retries=3, backoff=2):
    global _SHEETS_SERVICE
    import time
    from google.auth.exceptions import RefreshError, TransportError
    last_exc = None
    for attempt in range(max_retries):
        try:
            return fn()
        except RefreshError:
            _SHEETS_SERVICE = None  # token 失效，下次重建
            raise
        except TransportError as e:
            _SHEETS_SERVICE = None  # 網路問題，重建後重試
            last_exc = e
            if attempt < max_retries - 1:
                time.sleep(backoff ** attempt)
        except HttpError as e:
            last_exc = e
            if e.resp.status in (400, 404):
                raise
            if e.resp.status == 429:
                time.sleep((backoff ** attempt) + 1)
                continue
            if attempt < max_retries - 1:
                time.sleep(backoff ** attempt)
    raise last_exc


def _read(tab, range_):
    try:
        def _call():
            svc = _get_service()
            return svc.spreadsheets().values().get(
                spreadsheetId=_get_sheet_id(),
                range=f"{tab}!{range_}",
            ).execute()
        result = _retry_gapi(_call)
        return result.get("values", [])
    except HttpError as e:
        if e.resp.status in (400, 404):
            return []
        raise

def _append(tab, row):
    def _call():
        svc = _get_service()
        return svc.spreadsheets().values().append(
            spreadsheetId=_get_sheet_id(),
            range=f"{tab}!A1",
            valueInputOption="USER_ENTERED",
            body={"values": [row]},
        ).execute()
    try:
        _retry_gapi(_call)
    except HttpError as e:
        if e.resp.status in (400, 404):
            raise RuntimeError(f"Google Sheets 工作表「{tab}」不存在，請先建立該工作表") from e
        raise

def _update_cell(tab, cell, value):
    def _call():
        svc = _get_service()
        return svc.spreadsheets().values().update(
            spreadsheetId=_get_sheet_id(),
            range=f"{tab}!{cell}",
            valueInputOption="USER_ENTERED",
            body={"values": [[value]]},
        ).execute()
    try:
        _retry_gapi(_call)
    except HttpError as e:
        if e.resp.status in (400, 404):
            raise RuntimeError(f"Google Sheets 工作表「{tab}」不存在，請先建立該工作表") from e
        raise

# ── Background task queue (single worker thread to avoid thread explosion) ──
_bg_queue: "queue.Queue[tuple]" | None = None
_bg_thread: threading.Thread | None = None
_bg_lock = threading.Lock()


def _bg_worker():
    import queue
    while True:
        try:
            fn, args = _bg_queue.get(timeout=30)
        except queue.Empty:
            continue
        try:
            fn(*args)
        except Exception:
            logger.exception("bg task failed: %s", getattr(fn, "__name__", repr(fn)))
        finally:
            _bg_queue.task_done()


def bg(fn, *args):
    global _bg_queue, _bg_thread
    with _bg_lock:
        if _bg_queue is None:
            import queue
            _bg_queue = queue.Queue(maxsize=1000)
        if _bg_thread is None or not _bg_thread.is_alive():
            _bg_thread = threading.Thread(target=_bg_worker, daemon=True)
            _bg_thread.start()
    try:
        _bg_queue.put((fn, args), block=False)
    except Exception:
        logger.warning("bg queue full, dropping task: %s", getattr(fn, "__name__", repr(fn)))


# ──────────────────────────────────────────────
# 設定：取得成員清單
# ──────────────────────────────────────────────

def get_members() -> list[str]:
    cached = _sc_get("members", 300)  # 5 分鐘快取
    if cached is not None:
        return cached
    rows = _read("設定", "A2:A20")
    result = [r[0].strip() for r in rows if r and r[0].strip()]
    _sc_set("members", result)
    return result

def register_member(user_id: str, name: str):
    """把 LINE user_id 和名字寫進設定 tab，並更新快取"""
    rows = _read("設定", "A2:B30")
    svc = _get_service()
    sid = _get_sheet_id()
    # 找到同名或同 user_id 的行覆蓋，否則新增
    for i, r in enumerate(rows):
        row_name = r[0].strip() if r else ""
        row_uid = r[1].strip() if len(r) > 1 else ""
        if row_name == name or row_uid == user_id:
            svc.spreadsheets().values().update(
                spreadsheetId=sid,
                range=f"設定!A{i+2}:B{i+2}",
                valueInputOption="USER_ENTERED",
                body={"values": [[name, user_id]]},
            ).execute()
            _sc_del("members")
            return
    # 沒找到，新增一行
    _append("設定", [name, user_id])
    _sc_del("members")


# ── 簡易 key-value 設定（存在設定 tab E:F 欄）────

def get_setting(key: str, default=None):
    try:
        rows = _read("設定", "E2:F30")
        for r in rows:
            if len(r) >= 2 and r[0].strip() == key:
                return r[1].strip()
    except Exception:
        pass
    return default


def set_setting(key: str, value: str):
    try:
        rows = _read("設定", "E2:F30")
        for i, r in enumerate(rows):
            if len(r) >= 1 and r[0].strip() == key:
                _update_cell("設定", f"F{i+2}", value)
                return
        # 沒找到，新增一行
        _append("設定", [key, value])
    except Exception:
        pass


# ──────────────────────────────────────────────
# 家事清單 Tab: [任務名稱, 點數, 分類, 狀態, 完成者, 完成時間]
# ──────────────────────────────────────────────

def get_chores(only_pending=False) -> list[dict]:
    cache_key = "chores_pending" if only_pending else "chores_all"
    cached = _sc_get(cache_key, 120)  # 2 分鐘快取
    if cached is not None:
        return cached
    rows = _read("家事清單", "A2:F100")
    chores = []
    for i, r in enumerate(rows):
        if not r or not r[0].strip():
            continue
        chore = {
            "row": i + 2,
            "name": r[0].strip() if len(r) > 0 else "",
            "points": float(r[1]) if len(r) > 1 and r[1].strip().replace('.','',1).isdigit() else 1,
            "category": r[2].strip() if len(r) > 2 else "一般",
            "status": r[3].strip() if len(r) > 3 else "待完成",
            "done_by": r[4].strip() if len(r) > 4 else "",
            "done_at": r[5].strip() if len(r) > 5 else "",
        }
        if only_pending and chore["status"] == "已完成":
            continue
        chores.append(chore)
    _sc_set(cache_key, chores)
    return chores

# 每週點數上限設定（家事名稱 → 每週最多幾點）
WEEKLY_CAPS: dict[str, float] = {
    "掃地": 2.0,
}

# 家事別名對照（輸入 → 正式名稱）
CHORE_ALIASES: dict[str, str] = {
    # 地下室倒水（0.2）
    "倒水地下室":   "地下室倒水",
    "倒水（地下室）": "地下室倒水",
    "倒地下室水":   "地下室倒水",

    # 客房倒水（0.2）
    "客房除濕機倒水": "客房倒水",
    "倒水（客房）":  "客房倒水",
    "客房除濕":    "客房倒水",
    "倒客房水":    "客房倒水",

    # 一般倒水（0.1）— 其他除濕機、客廳等
    "倒水（除濕機）": "倒水",
    "倒水除濕機":   "倒水",

    # 電風扇清潔
    "洗電扇":     "洗電風扇",
    "清電風扇":    "洗電風扇",

    # 資源回收
    "收資源回收":   "資源回收",
    "資源垃圾":    "資源回收",
}

_WEEKLY_POINTS_CACHE: dict[tuple[str, str], tuple[float, float]] = {}
_WEEKLY_CACHE_TTL = 60.0

def get_member_weekly_chore_points(member: str, chore_name: str) -> float:
    """查詢本週某成員在某項家事累積的點數（帶 60 秒快取）"""
    import time
    key = (member, chore_name)
    now = time.time()
    cached = _WEEKLY_POINTS_CACHE.get(key)
    if cached is not None:
        value, ts = cached
        if now - ts < _WEEKLY_CACHE_TTL:
            return value
    rows = _read("點數記錄", "A2:D500")
    week_start = _week_start()
    total = 0.0
    for r in rows:
        if len(r) < 4:
            continue
        if r[0] >= week_start and r[1] == member and r[2] == chore_name:
            try:
                total += float(r[3])
            except ValueError:
                pass
    _WEEKLY_POINTS_CACHE[key] = (total, now)
    return total

def find_chore(chore_name: str) -> dict | None:
    """查詢家事名稱對應的設定（不寫入）"""
    chore_name = CHORE_ALIASES.get(chore_name, chore_name)
    chores = get_chores()
    matched = next(
        (c for c in chores if chore_name in c["name"] or c["name"] in chore_name),
        None,
    )
    return matched

def complete_chore(chore_name: str, member: str) -> dict | None:
    """家事可重複做，查名稱、檢查上限、回傳結果（不寫入 Sheets）"""
    matched = find_chore(chore_name)
    if not matched:
        return None

    cap = WEEKLY_CAPS.get(matched["name"])
    if cap is not None:
        already = get_member_weekly_chore_points(member, matched["name"])
        if already >= cap:
            matched["capped"] = True
            matched["cap"] = cap
            return matched

    matched["capped"] = False
    return matched

def log_chore_points(member: str, chore_name: str, points: float):
    """將家事點數寫入 Sheets（可放 background thread）"""
    _append("點數記錄", [_today_str(), member, chore_name, points, _now_str()])
    _sc_del("weekly_points")

def add_chore(name: str, points: float = 1, category: str = "一般"):
    _append("家事清單", [name, points, category, "待完成", "", ""])
    _sc_del("chores_all", "chores_pending")

def batch_log_points(member: str, chores: list[tuple[str, float]]):
    """批量記點，一次寫入所有家事"""
    today = _today_str()
    now = _now_str()
    rows = [[today, member, name, pts, now] for name, pts in chores]
    svc = _get_service()
    svc.spreadsheets().values().append(
        spreadsheetId=_get_sheet_id(),
        range="點數記錄!A1",
        valueInputOption="USER_ENTERED",
        body={"values": rows},
    ).execute()
    _sc_del("weekly_points")

def reset_chore(chore_name: str):
    """重置家事為待完成（每日/每週循環用）"""
    chores = get_chores()
    for c in chores:
        if c["name"] == chore_name and c["status"] == "已完成":
            svc = _get_service()
            svc.spreadsheets().values().update(
                spreadsheetId=_get_sheet_id(),
                range=f"家事清單!D{c['row']}:F{c['row']}",
                valueInputOption="USER_ENTERED",
                body={"values": [["待完成", "", ""]]},
            ).execute()


# ──────────────────────────────────────────────
# 點數記錄 Tab: [日期, 成員, 任務, 點數, 時間]
# ──────────────────────────────────────────────

def cancel_last_record(member: str, chore_name: str = None) -> dict | None:
    """取消某成員最近一筆記錄；指定 chore_name 則只取消那項家事"""
    rows = _read("點數記錄", "A2:E500")
    target_idx = None
    for i in range(len(rows) - 1, -1, -1):
        r = rows[i]
        if len(r) < 4:
            continue
        if r[1] == member:
            if chore_name is None or chore_name in r[2] or r[2] in chore_name:
                target_idx = i
                break
    if target_idx is None:
        return None
    removed = rows[target_idx]
    keep_rows = rows[:target_idx] + rows[target_idx + 1:]
    svc = _get_service()
    sid = _get_sheet_id()
    svc.spreadsheets().values().clear(spreadsheetId=sid, range="點數記錄!A2:E500").execute()
    if keep_rows:
        svc.spreadsheets().values().update(
            spreadsheetId=sid, range="點數記錄!A2",
            valueInputOption="USER_ENTERED", body={"values": keep_rows},
        ).execute()
    return {
        "name": removed[2] if len(removed) > 2 else "",
        "points": float(removed[3]) if len(removed) > 3 else 0,
    }


def get_last_week_points() -> dict[str, float]:
    """回傳上週每位成員的累積點數"""
    rows = _read("點數記錄", "A2:D500")
    d = datetime.now(TW_TZ).date()
    this_monday = d - timedelta(days=d.weekday())
    last_monday = this_monday - timedelta(days=7)
    week_start = last_monday.strftime("%Y-%m-%d")
    week_end = (this_monday - timedelta(days=1)).strftime("%Y-%m-%d")
    totals: dict[str, float] = {}
    for r in rows:
        if not r or len(r) < 4:
            continue
        date_str, member, _, pts = r[0], r[1], r[2], r[3]
        if week_start <= date_str <= week_end:
            try:
                totals[member] = round(totals.get(member, 0.0) + float(pts), 2)
            except ValueError:
                pass
    return totals


def get_member_weekly_breakdown(member: str) -> list[dict]:
    """回傳本週某成員每項家事的累積點數"""
    rows = _read("點數記錄", "A2:D500")
    week_start = _week_start()
    breakdown: dict[str, float] = {}
    for r in rows:
        if not r or len(r) < 4:
            continue
        date_str, m, chore, pts = r[0], r[1], r[2], r[3]
        if date_str >= week_start and m == member:
            try:
                breakdown[chore] = breakdown.get(chore, 0.0) + float(pts)
            except ValueError:
                pass
    return [{"name": k, "points": v} for k, v in breakdown.items()]

def get_weekly_points() -> dict[str, float]:
    """回傳本週每位成員的累積點數"""
    cached = _sc_get("weekly_points", 120)  # 2 分鐘快取
    if cached is not None:
        return cached
    rows = _read("點數記錄", "A2:D500")
    week_start = _week_start()
    totals: dict[str, float] = {}
    for r in rows:
        if not r or len(r) < 4:
            continue
        date_str, member, _, pts = r[0], r[1], r[2], r[3]
        if date_str >= week_start:
            try:
                totals[member] = round(totals.get(member, 0.0) + float(pts), 2)
            except ValueError:
                pass
    _sc_set("weekly_points", totals)
    return totals

def format_weekly_summary() -> str:
    """格式化本週點數總覽：固定成員 + 本週有記點的人都顯示"""
    pts = get_weekly_points()
    members = get_members()
    # 合併：固定成員 + 本週有記點但不在清單裡的人
    all_names = list(members)
    for name in pts:
        if name not in all_names and name != "不知道誰":
            all_names.append(name)
    lines = ["📊 本週點數統計："]
    for m in all_names:
        p = pts.get(m, 0.0)
        p_str = f"{p:.2f}".rstrip('0').rstrip('.')
        lines.append(f"{m}  {p_str}")
    return "\n".join(lines)


# ──────────────────────────────────────────────
# 購物清單 Tab: [項目, 加入者, 加入時間, 狀態, 完成者, 完成時間]
# ──────────────────────────────────────────────

def get_shopping_list(only_pending=True) -> list[dict]:
    rows = _read("購物清單", "A2:F200")
    items = []
    for i, r in enumerate(rows):
        if not r or not r[0].strip():
            continue
        item = {
            "row": i + 2,
            "name": r[0].strip(),
            "added_by": r[1].strip() if len(r) > 1 else "",
            "added_at": r[2].strip() if len(r) > 2 else "",
            "status": r[3].strip() if len(r) > 3 else "未買",
            "done_by": r[4].strip() if len(r) > 4 else "",
            "done_at": r[5].strip() if len(r) > 5 else "",
        }
        if only_pending and item["status"] == "已買":
            continue
        items.append(item)
    return items

def add_shopping(item_name: str, member: str):
    _append("購物清單", [item_name, member, _now_str(), "未買", "", ""])

def find_shopping_item(item_name: str) -> dict | None:
    """查詢購物項目（不寫入）"""
    items = get_shopping_list(only_pending=True)
    return next(
        (it for it in items if item_name in it["name"] or it["name"] in item_name),
        None,
    )

def complete_shopping(item_name: str, member: str) -> bool:
    """標記購物項目為已買（寫入 Sheets）"""
    matched = find_shopping_item(item_name)
    if not matched:
        return False
    mark_shopping_done(matched["row"], member)
    return True

def mark_shopping_done(row: int, member: str):
    """更新購物清單狀態為已買（可放 background thread）"""
    svc = _get_service()
    svc.spreadsheets().values().update(
        spreadsheetId=_get_sheet_id(),
        range=f"購物清單!D{row}:F{row}",
        valueInputOption="USER_ENTERED",
        body={"values": [["已買", member, _now_str()]]},
    ).execute()


# ──────────────────────────────────────────────
# 記帳 Tab: [日期, 金額, 分類, 說明, 記錄者]
# ──────────────────────────────────────────────

def add_expense(amount: int, category: str, description: str, member: str):
    _append("記帳", [_today_str(), amount, category, description, member, _now_str()])

def add_income(amount: int, description: str, member: str):
    """斷捨離賣出收入，記入記帳 tab，分類為斷捨離收入"""
    _append("記帳", [_today_str(), amount, "斷捨離收入", description, member, _now_str()])

def get_declutter_income() -> list[dict]:
    """查所有斷捨離收入記錄"""
    rows = _read("記帳", "A2:F500")
    result = []
    for r in rows:
        if not r or len(r) < 4:
            continue
        if len(r) > 2 and r[2] == "斷捨離收入":
            result.append({
                "date": r[0],
                "amount": int(r[1]) if str(r[1]).strip().isdigit() else 0,
                "desc": r[3] if len(r) > 3 else "",
                "by": r[4] if len(r) > 4 else "",
            })
    return result

# ──────────────────────────────────────────────
# 斷捨離 Tab: [物品, 加入者, 加入時間, 狀態, 處理方式, 金額, 處理者, 處理時間]
# ──────────────────────────────────────────────

def add_declutter(item: str, member: str):
    _append("斷捨離", [item, member, _now_str(), "待定", "", "", "", ""])

def get_declutter_list(only_pending=True) -> list[dict]:
    rows = _read("斷捨離", "A2:H200")
    result = []
    for i, r in enumerate(rows):
        if not r or not r[0].strip():
            continue
        item = {
            "row": i + 2,
            "name": r[0].strip(),
            "added_by": r[1].strip() if len(r) > 1 else "",
            "added_at": r[2].strip() if len(r) > 2 else "",
            "status": r[3].strip() if len(r) > 3 else "待定",
            "method": r[4].strip() if len(r) > 4 else "",
            "amount": r[5].strip() if len(r) > 5 else "",
            "done_by": r[6].strip() if len(r) > 6 else "",
            "done_at": r[7].strip() if len(r) > 7 else "",
        }
        if only_pending and item["status"] != "待定":
            continue
        result.append(item)
    return result

def get_weekly_declutter_stats() -> dict[str, dict]:
    """本週斷捨離統計：每人完成件數 + 賣出金額"""
    rows = _read("斷捨離", "A2:H200")
    week_start = _week_start()
    stats: dict[str, dict] = {}
    for r in rows:
        if len(r) < 7:
            continue
        status = r[3].strip() if len(r) > 3 else ""
        done_by = r[6].strip() if len(r) > 6 else ""
        done_at = r[7].strip() if len(r) > 7 else ""
        if status in ("丟棄", "賣出") and done_by and done_at >= week_start:
            if done_by not in stats:
                stats[done_by] = {"count": 0, "income": 0}
            stats[done_by]["count"] += 1
            if status == "賣出":
                try:
                    stats[done_by]["income"] += int(str(r[5]).strip()) if len(r) > 5 and r[5] else 0
                except (ValueError, TypeError):
                    pass
    return stats


def complete_declutter(item_name: str, method: str, member: str, amount: int = 0) -> dict | None:
    items = get_declutter_list(only_pending=True)
    matched = next(
        (it for it in items if item_name in it["name"] or it["name"] in item_name),
        None,
    )
    if not matched:
        return None
    svc = _get_service()
    svc.spreadsheets().values().update(
        spreadsheetId=_get_sheet_id(),
        range=f"斷捨離!D{matched['row']}:H{matched['row']}",
        valueInputOption="USER_ENTERED",
        body={"values": [[method, "", amount if amount else "", member, _now_str()]]},
    ).execute()
    matched["method"] = method
    matched["amount"] = amount
    return matched

# ──────────────────────────────────────────────
# 欠款 Tab: [日期, 成員, 類型(罰款/繳款), 金額, 說明]
# ──────────────────────────────────────────────

def add_fine(member: str, week_label: str, points: float, amount: int):
    desc = f"{week_label}週 點數{points:.1f}點不足"
    _append("欠款", [_today_str(), member, "罰款", amount, desc])

def pay_fine(member: str, amount: int):
    _append("欠款", [_today_str(), member, "繳款", amount, "投幣繳款"])

def get_outstanding_fines(member: str = None) -> dict[str, int]:
    """回傳每人累積未繳金額（正數=欠款）"""
    rows = _read("欠款", "A2:E500")
    balances: dict[str, int] = {}
    for r in rows:
        if len(r) < 4:
            continue
        m, type_, amt = r[1], r[2], r[3]
        try:
            amt_int = int(str(amt).strip())
        except (ValueError, TypeError):
            continue
        if type_ == "罰款":
            balances[m] = balances.get(m, 0) + amt_int
        elif type_ == "繳款":
            balances[m] = balances.get(m, 0) - amt_int
    if member:
        return {member: balances.get(member, 0)}
    return {m: v for m, v in balances.items() if v != 0}


def get_expenses(days: int = 7) -> list[dict]:
    rows = _read("記帳", "A2:F500")
    cutoff = (datetime.now(TW_TZ) - timedelta(days=days)).strftime("%Y-%m-%d")
    result = []
    for r in rows:
        if not r or len(r) < 4:
            continue
        if r[0] >= cutoff:
            result.append({
                "date": r[0],
                "amount": int(r[1]) if r[1].strip().isdigit() else 0,
                "category": r[2] if len(r) > 2 else "",
                "desc": r[3] if len(r) > 3 else "",
                "by": r[4] if len(r) > 4 else "",
            })
    return result


# ──────────────────────────────────────────────
# 收拾紀錄 Tab: [日期, 時間, 成員, 區域(自己/公共), 內容]
# ──────────────────────────────────────────────

_SELF_AREA_KEYWORDS = ["自己", "我的", "房間", "書桌", "書房", "臥室", "房間", "衣櫃", "抽屜", "床鋪", "床邊"]
_PUBLIC_AREA_KEYWORDS = ["公共", "客廳", "廚房", "玄關", "陽台", "走廊", "餐廳", "浴室", "廁所", "樓梯", "大門"]


_TIDY_TAB_ENSURED = False


def _ensure_tidy_tab():
    """確保「收拾紀錄」工作表存在，不存在則自動建立"""
    global _TIDY_TAB_ENSURED
    if _TIDY_TAB_ENSURED:
        return
    svc = _get_service()
    sid = _get_sheet_id()
    meta = svc.spreadsheets().get(spreadsheetId=sid).execute()
    titles = [s["properties"]["title"] for s in meta.get("sheets", [])]
    if "收拾紀錄" not in titles:
        svc.spreadsheets().batchUpdate(
            spreadsheetId=sid,
            body={
                "requests": [
                    {
                        "addSheet": {
                            "properties": {
                                "title": "收拾紀錄",
                                "gridProperties": {"rowCount": 1000, "columnCount": 5},
                            }
                        }
                    }
                ]
            },
        ).execute()
        svc.spreadsheets().values().update(
            spreadsheetId=sid,
            range="收拾紀錄!A1:E1",
            valueInputOption="USER_ENTERED",
            body={"values": [["日期", "時間", "成員", "區域", "內容"]]},
        ).execute()
    _TIDY_TAB_ENSURED = True


def _detect_area(text: str) -> str:
    """偵測收拾區域：自己 / 公共 / 未分類"""
    text = text.lower()
    for k in _SELF_AREA_KEYWORDS:
        if k in text:
            return "自己"
    for k in _PUBLIC_AREA_KEYWORDS:
        if k in text:
            return "公共"
    return "未分類"


def add_tidy_log(member: str, area: str, content: str):
    """記錄一次收拾"""
    _ensure_tidy_tab()
    _append("收拾紀錄", [_today_str(), _now_str(), member, area, content])


def get_today_tidy_logs() -> dict[str, list[dict]]:
    """回傳今天全家的收拾記錄，按成員分組"""
    rows = _read("收拾紀錄", "A2:E1000")
    today = _today_str()
    result: dict[str, list[dict]] = {}
    for r in rows:
        if not r or len(r) < 5:
            continue
        if r[0] != today:
            continue
        member = r[2] if len(r) > 2 else ""
        entry = {
            "time": r[1] if len(r) > 1 else "",
            "area": r[3] if len(r) > 3 else "",
            "content": r[4] if len(r) > 4 else "",
        }
        result.setdefault(member, []).append(entry)
    return result


def get_tidy_logs(days: int = 7) -> dict[str, dict[str, list[dict]]]:
    """回傳最近 N 天每天的收拾記錄，按日期→成員分組"""
    rows = _read("收拾紀錄", "A2:E1000")
    cutoff = (datetime.now(TW_TZ) - timedelta(days=days)).strftime("%Y-%m-%d")
    result: dict[str, dict[str, list[dict]]] = {}
    for r in rows:
        if not r or len(r) < 5:
            continue
        date = r[0]
        if date < cutoff:
            continue
        member = r[2] if len(r) > 2 else ""
        entry = {
            "time": r[1] if len(r) > 1 else "",
            "area": r[3] if len(r) > 3 else "",
            "content": r[4] if len(r) > 4 else "",
        }
        result.setdefault(date, {}).setdefault(member, []).append(entry)
    return result


def get_today_tidy_type_count(member: str) -> dict[str, int]:
    """回傳某成員今天各類型收拾次數，用於每日上限判斷。"""
    logs = get_today_tidy_logs()
    entries = logs.get(member, [])
    return {
        "自己": sum(1 for e in entries if e["area"] == "自己"),
        "公共": sum(1 for e in entries if e["area"] == "公共"),
    }


def get_tidy_debt() -> dict[str, dict[str, int]]:
    """回傳每人本週還需收拾幾天。
    = 過去已錯過天數（週一到今天）+ 本週剩餘天數（今天之後到週日）。
    最少 = 剩餘天數（全勤時），最多 = 7（一天都沒做）。
    """
    today = datetime.now(TW_TZ).date()
    days_since_monday = today.weekday()      # 0=週一，6=週日
    days_elapsed = days_since_monday + 1     # 本週已過幾天（含今天）
    remaining_days = 6 - days_since_monday   # 今天之後還剩幾天（週日=0）
    week_start_str = (today - timedelta(days=days_since_monday)).strftime("%Y-%m-%d")

    logs = get_tidy_logs(days_elapsed + 1)
    members = ["爸爸", "媽媽", "姊姊", "妹妹"]
    past_missed = {m: {"自己": 0, "公共": 0} for m in members}
    makeup = {m: {"自己": 0, "公共": 0} for m in members}

    # 補收拾次數（本週內）
    for date_str, day_logs in logs.items():
        if date_str < week_start_str:
            continue
        for m in members:
            for e in day_logs.get(m, []):
                if e["area"] == "補自己":
                    makeup[m]["自己"] += 1
                elif e["area"] == "補公共":
                    makeup[m]["公共"] += 1

    # 過去已錯過天數（週一到今天）
    for offset in range(days_elapsed):
        date = (today - timedelta(days=offset)).strftime("%Y-%m-%d")
        if date < week_start_str:
            continue
        day_logs = logs.get(date, {})
        for m in members:
            entries = day_logs.get(m, [])
            if not any(e["area"] == "自己" for e in entries):
                past_missed[m]["自己"] += 1
            if not any(e["area"] == "公共" for e in entries):
                past_missed[m]["公共"] += 1

    # 總欠 = 過去錯過（扣補收拾）+ 後面還剩幾天
    debt = {}
    for m in members:
        debt[m] = {
            "自己": max(0, past_missed[m]["自己"] - makeup[m]["自己"]) + remaining_days,
            "公共": max(0, past_missed[m]["公共"] - makeup[m]["公共"]) + remaining_days,
        }
    return debt


def format_tidy_summary() -> str:
    """格式化今天全家收拾紀錄 + 欠次提示"""
    logs = get_today_tidy_logs()
    debt = get_tidy_debt()
    lines = []
    if not logs:
        lines.append("今天還沒有人報備收拾紀錄喔！\n")
    else:
        lines.append("🧹 今天全家收拾紀錄\n")
        for member in ["爸爸", "媽媽", "姊姊", "妹妹"]:
            if member not in logs:
                continue
            entries = logs[member]
            self_count = sum(1 for e in entries if e["area"] == "自己")
            pub_count = sum(1 for e in entries if e["area"] == "公共")
            makeup_count = sum(1 for e in entries if e["area"] in ("補自己", "補公共"))
            other_count = len(entries) - self_count - pub_count - makeup_count
            badge = []
            if self_count:
                badge.append(f"自己×{self_count}")
            if pub_count:
                badge.append(f"公共×{pub_count}")
            if makeup_count:
                badge.append(f"補×{makeup_count}")
            if other_count:
                badge.append(f"其他×{other_count}")
            lines.append(f"【{member}】{' / '.join(badge) if badge else '無紀錄'}")
            for e in entries:
                if e["area"] == "自己":
                    area_emoji = "🏠"
                elif e["area"] == "公共":
                    area_emoji = "🛋"
                elif e["area"] in ("補自己", "補公共"):
                    area_emoji = "📝"
                else:
                    area_emoji = "📦"
                lines.append(f"  {area_emoji} {e['content']}")
            lines.append("")
    # 欠次提示
    today_wd = datetime.now(TW_TZ).weekday()
    weekday_names = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]
    lines.append(f"\n📊 本週欠收拾統計（週一到{weekday_names[today_wd]}，共{today_wd + 1}天）")
    for member in ["爸爸", "媽媽", "姊姊", "妹妹"]:
        d = debt.get(member, {"自己": 0, "公共": 0})
        if d["自己"] == 0 and d["公共"] == 0:
            lines.append(f"✅ {member}：本週全勤！")
        else:
            parts = []
            if d["自己"]:
                parts.append(f"自己欠{d['自己']}天")
            if d["公共"]:
                parts.append(f"公共欠{d['公共']}天")
            lines.append(f"⚠️ {member}：{' / '.join(parts)}")
    lines.append("\n傳「收拾 [內容]」記錄今日（自己/公共各限1次）\n傳「補收拾 [內容]」補記過去欠下的（需有欠才能補）")
    return "\n".join(lines)


def rename_tidy_member(old_name: str, new_name: str) -> list[dict]:
    """批次修正「收拾紀錄」中的成員名稱，回傳修改明細列表"""
    svc = _get_service()
    sid = _get_sheet_id()
    rows = _read("收拾紀錄", "A2:E1000")
    changed: list[dict] = []
    for i, r in enumerate(rows):
        if len(r) >= 3 and r[2] == old_name:
            row_num = i + 2  # A2 開始
            svc.spreadsheets().values().update(
                spreadsheetId=sid,
                range=f"收拾紀錄!C{row_num}",
                valueInputOption="USER_ENTERED",
                body={"values": [[new_name]]},
            ).execute()
            changed.append({
                "date": r[0] if len(r) > 0 else "",
                "time": r[1] if len(r) > 1 else "",
                "area": r[3] if len(r) > 3 else "",
                "content": r[4] if len(r) > 4 else "",
            })
    return changed


def rename_latest_tidy_member(old_name: str, new_name: str) -> dict | None:
    """只修正「收拾紀錄」中最新一筆符合的成員名稱，回傳該筆明細或 None"""
    svc = _get_service()
    sid = _get_sheet_id()
    rows = _read("收拾紀錄", "A2:E1000")
    # 從底部往上找最新一筆
    for i in range(len(rows) - 1, -1, -1):
        r = rows[i]
        if len(r) >= 3 and r[2] == old_name:
            row_num = i + 2  # A2 開始
            svc.spreadsheets().values().update(
                spreadsheetId=sid,
                range=f"收拾紀錄!C{row_num}",
                valueInputOption="USER_ENTERED",
                body={"values": [[new_name]]},
            ).execute()
            return {
                "date": r[0] if len(r) > 0 else "",
                "time": r[1] if len(r) > 1 else "",
                "area": r[3] if len(r) > 3 else "",
                "content": r[4] if len(r) > 4 else "",
            }
    return None


# ─── Todo / Reminder ──────────────────────────────────────

_TODO_SHEET_ID: int | None = None


def _get_todo_sheet_id() -> int | None:
    """Return the numeric sheetId for the 待辦 tab (cached after first fetch)."""
    global _TODO_SHEET_ID
    if _TODO_SHEET_ID is not None:
        return _TODO_SHEET_ID
    svc = _get_service()
    sid = _get_sheet_id()
    meta = svc.spreadsheets().get(spreadsheetId=sid).execute()
    for s in meta.get("sheets", []):
        if s["properties"]["title"] == "待辦":
            _TODO_SHEET_ID = s["properties"]["sheetId"]
            return _TODO_SHEET_ID
    return None


def get_todos(only_pending=True) -> list[dict]:
    cache_key = "todos_pending" if only_pending else "todos_all"
    cached = _sc_get(cache_key, 60)  # 60s cache
    if cached is not None:
        return cached
    try:
        rows = _read("待辦", "A2:H200")
    except Exception:
        return []
    items = []
    for i, r in enumerate(rows):
        if not r or not r[0].strip():
            continue
        item = {
            "row": i + 2,
            "timestamp":     r[0].strip() if len(r) > 0 else "",
            "date":          r[1].strip() if len(r) > 1 else "",
            "member":        r[2].strip() if len(r) > 2 else "",
            "content":       r[3].strip() if len(r) > 3 else "",
            "status":        r[4].strip() if len(r) > 4 else "待辦",
            "created_by":    r[5].strip() if len(r) > 5 else "",
            "time":          r[6].strip() if len(r) > 6 else "",
            "reminded_count": int(r[7]) if len(r) > 7 and str(r[7]).strip().isdigit() else 0,
        }
        if only_pending and item["status"] == "已完成":
            continue
        items.append(item)
    _sc_set(cache_key, items)
    return items


def add_todo(member: str, date_str: str, content: str, created_by: str,
             time_str: str = "") -> bool:
    try:
        _ensure_tab("待辦")
        _append("待辦", [_now_str(), date_str, member, content, "待辦", created_by,
                         time_str, 0])
        _sc_del("todos_pending", "todos_all")
        return True
    except Exception as e:
        logger.warning("add_todo failed: %s", e)
        return False


def update_todo_reminder(row: int, reminded_count: int):
    """更新待辦的提醒次數（column H）。"""
    _update_cell("待辦", f"H{row}", reminded_count)
    _sc_del("todos_pending", "todos_all")


def find_todos_by_content(member: str, content: str) -> list[dict]:
    """Find all pending todos matching content. Returns list of todo dicts."""
    try:
        todos = get_todos(only_pending=True)
        return [t for t in todos if content in t["content"] or t["content"] in content]
    except Exception as e:
        logger.warning("find_todos_by_content failed: %s", e)
        return []


def complete_todo_by_content(member: str, content: str) -> dict | None:
    """Mark matching pending todo as done. Returns todo dict or None."""
    matched = find_todos_by_content(member, content)
    if not matched:
        return None
    if len(matched) > 1:
        return {"multiple": True, "items": matched}
    try:
        _update_cell("待辦", f"E{matched[0]['row']}", "已完成")
        _sc_del("todos_pending", "todos_all")
        return matched[0]
    except Exception as e:
        logger.warning("complete_todo_by_content failed: %s", e)
        return None


def delete_todo_by_row(row: int) -> bool:
    """Delete a todo row by its row number. Returns True on success."""
    try:
        sheet_id = _get_todo_sheet_id()
        if sheet_id is None:
            return False
        svc = _get_service()
        sid = _get_sheet_id()
        row_index = row - 1
        svc.spreadsheets().batchUpdate(
            spreadsheetId=sid,
            body={
                "requests": [{
                    "deleteDimension": {
                        "range": {
                            "sheetId": sheet_id,
                            "dimension": "ROWS",
                            "startIndex": row_index,
                            "endIndex": row_index + 1,
                        }
                    }
                }]
            },
        ).execute()
        _sc_del("todos_pending", "todos_all")
        return True
    except Exception as e:
        logger.warning("delete_todo_by_row failed: %s", e)
        return False


def delete_todo_by_content(member: str, content: str) -> dict | None:
    """Delete matching pending todo row completely. Returns todo dict or None."""
    matched = find_todos_by_content(member, content)
    if not matched:
        return None
    if len(matched) > 1:
        return {"multiple": True, "items": matched}
    if delete_todo_by_row(matched[0]["row"]):
        return matched[0]
    return None
