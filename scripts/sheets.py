"""
Google Sheets helper — 家庭群機器人資料層
Tabs: 家事清單, 點數記錄, 購物清單, 記帳, 設定
"""

import os
import json
import threading
from datetime import datetime, timezone, timedelta
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

TW_TZ = timezone(timedelta(hours=8))

def _now_str():
    return datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M")

def _today_str():
    return datetime.now(TW_TZ).strftime("%Y-%m-%d")

def _week_start():
    d = datetime.now(TW_TZ).date()
    return (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")

def _get_service():
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")
    if creds_json:
        info = json.loads(creds_json)
    else:
        info = {
            "client_id": os.environ["GOOGLE_CLIENT_ID"],
            "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
            "refresh_token": os.environ["GOOGLE_REFRESH_TOKEN"],
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    creds = Credentials(
        token=None,
        refresh_token=info["refresh_token"],
        token_uri=info["token_uri"],
        client_id=info["client_id"],
        client_secret=info["client_secret"],
    )
    return build("sheets", "v4", credentials=creds, cache_discovery=False)

def _get_sheet_id():
    return os.environ["FAMILY_SHEET_ID"]

def _read(tab, range_):
    svc = _get_service()
    result = svc.spreadsheets().values().get(
        spreadsheetId=_get_sheet_id(),
        range=f"{tab}!{range_}",
    ).execute()
    return result.get("values", [])

def _append(tab, row):
    svc = _get_service()
    svc.spreadsheets().values().append(
        spreadsheetId=_get_sheet_id(),
        range=f"{tab}!A1",
        valueInputOption="USER_ENTERED",
        body={"values": [row]},
    ).execute()

def _update_cell(tab, cell, value):
    svc = _get_service()
    svc.spreadsheets().values().update(
        spreadsheetId=_get_sheet_id(),
        range=f"{tab}!{cell}",
        valueInputOption="USER_ENTERED",
        body={"values": [[value]]},
    ).execute()

def bg(fn, *args):
    threading.Thread(target=fn, args=args, daemon=True).start()


# ──────────────────────────────────────────────
# 設定：取得成員清單
# ──────────────────────────────────────────────

def get_members() -> list[str]:
    rows = _read("設定", "A2:A20")
    return [r[0].strip() for r in rows if r and r[0].strip()]


# ──────────────────────────────────────────────
# 家事清單 Tab: [任務名稱, 點數, 分類, 狀態, 完成者, 完成時間]
# ──────────────────────────────────────────────

def get_chores(only_pending=False) -> list[dict]:
    rows = _read("家事清單", "A2:F100")
    chores = []
    for i, r in enumerate(rows):
        if not r or not r[0].strip():
            continue
        chore = {
            "row": i + 2,
            "name": r[0].strip() if len(r) > 0 else "",
            "points": int(r[1]) if len(r) > 1 and r[1].strip().isdigit() else 1,
            "category": r[2].strip() if len(r) > 2 else "一般",
            "status": r[3].strip() if len(r) > 3 else "待完成",
            "done_by": r[4].strip() if len(r) > 4 else "",
            "done_at": r[5].strip() if len(r) > 5 else "",
        }
        if only_pending and chore["status"] == "已完成":
            continue
        chores.append(chore)
    return chores

def complete_chore(chore_name: str, member: str) -> dict | None:
    chores = get_chores(only_pending=True)
    matched = next(
        (c for c in chores if chore_name in c["name"] or c["name"] in chore_name),
        None,
    )
    if not matched:
        return None
    row = matched["row"]
    svc = _get_service()
    sid = _get_sheet_id()
    svc.spreadsheets().values().update(
        spreadsheetId=sid,
        range=f"家事清單!D{row}:F{row}",
        valueInputOption="USER_ENTERED",
        body={"values": [["已完成", member, _now_str()]]},
    ).execute()
    # Reset next day (add as pending again for recurring chores)
    # Also log points
    _append("點數記錄", [_today_str(), member, matched["name"], matched["points"], _now_str()])
    return matched

def add_chore(name: str, points: int = 1, category: str = "一般"):
    _append("家事清單", [name, points, category, "待完成", "", ""])

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

def get_weekly_points() -> dict[str, int]:
    """回傳本週每位成員的累積點數"""
    rows = _read("點數記錄", "A2:D500")
    week_start = _week_start()
    totals: dict[str, int] = {}
    for r in rows:
        if not r or len(r) < 4:
            continue
        date_str, member, _, pts = r[0], r[1], r[2], r[3]
        if date_str >= week_start:
            try:
                totals[member] = totals.get(member, 0) + int(pts)
            except ValueError:
                pass
    return totals


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

def complete_shopping(item_name: str, member: str) -> bool:
    items = get_shopping_list(only_pending=True)
    matched = next(
        (it for it in items if item_name in it["name"] or it["name"] in item_name),
        None,
    )
    if not matched:
        return False
    svc = _get_service()
    svc.spreadsheets().values().update(
        spreadsheetId=_get_sheet_id(),
        range=f"購物清單!D{matched['row']}:F{matched['row']}",
        valueInputOption="USER_ENTERED",
        body={"values": [["已買", member, _now_str()]]},
    ).execute()
    return True


# ──────────────────────────────────────────────
# 記帳 Tab: [日期, 金額, 分類, 說明, 記錄者]
# ──────────────────────────────────────────────

def add_expense(amount: int, category: str, description: str, member: str):
    _append("記帳", [_today_str(), amount, category, description, member, _now_str()])

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
