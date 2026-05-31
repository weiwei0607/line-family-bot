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
            return
    # 沒找到，新增一行
    _append("設定", [name, user_id])


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
            "points": float(r[1]) if len(r) > 1 and r[1].strip().replace('.','',1).isdigit() else 1,
            "category": r[2].strip() if len(r) > 2 else "一般",
            "status": r[3].strip() if len(r) > 3 else "待完成",
            "done_by": r[4].strip() if len(r) > 4 else "",
            "done_at": r[5].strip() if len(r) > 5 else "",
        }
        if only_pending and chore["status"] == "已完成":
            continue
        chores.append(chore)
    return chores

# 每週點數上限設定（家事名稱 → 每週最多幾點）
WEEKLY_CAPS: dict[str, float] = {
    "掃地": 2.0,
}

def get_member_weekly_chore_points(member: str, chore_name: str) -> float:
    """查詢本週某成員在某項家事累積的點數"""
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
    return total

def complete_chore(chore_name: str, member: str) -> dict | None:
    """家事可重複做，直接查名稱記點，不改狀態欄位"""
    chores = get_chores()  # 不限狀態，只要名稱符合就算
    matched = next(
        (c for c in chores if chore_name in c["name"] or c["name"] in chore_name),
        None,
    )
    if not matched:
        return None

    # 檢查每週上限
    cap = WEEKLY_CAPS.get(matched["name"])
    if cap is not None:
        already = get_member_weekly_chore_points(member, matched["name"])
        if already >= cap:
            matched["capped"] = True
            matched["cap"] = cap
            return matched

    _append("點數記錄", [_today_str(), member, matched["name"], matched["points"], _now_str()])
    matched["capped"] = False
    return matched

def add_chore(name: str, points: float = 1, category: str = "一般"):
    _append("家事清單", [name, points, category, "待完成", "", ""])

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
    rows = _read("點數記錄", "A2:D500")
    week_start = _week_start()
    totals: dict[str, float] = {}
    for r in rows:
        if not r or len(r) < 4:
            continue
        date_str, member, _, pts = r[0], r[1], r[2], r[3]
        if date_str >= week_start:
            try:
                totals[member] = totals.get(member, 0.0) + float(pts)
            except ValueError:
                pass
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
        body={"values": [[method, amount if amount else "", member, _now_str(), ""]]},
    ).execute()
    matched["method"] = method
    matched["amount"] = amount
    return matched

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
