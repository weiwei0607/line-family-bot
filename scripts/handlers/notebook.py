"""
Shared notebook — LINE Keep replacement using Google Sheets.
Uses the existing sheets.py service.
"""

import re
from sheets import _get_service, _get_sheet_id, _ensure_tab, TW_TZ
from datetime import datetime

_TAB = "記事本"


def _today():
    return datetime.now(TW_TZ).strftime("%Y-%m-%d")


def _now():
    return datetime.now(TW_TZ).strftime("%H:%M")


def _append_row(row):
    svc = _get_service()
    if not svc:
        return False
    _ensure_tab(_TAB)
    try:
        svc.spreadsheets().values().append(
            spreadsheetId=_get_sheet_id(),
            range=f"{_TAB}!A1",
            valueInputOption="USER_ENTERED",
            body={"values": [row]},
        ).execute()
        return True
    except Exception as e:
        print(f"[Notebook] Append failed: {e}")
        return False


def _read_all():
    svc = _get_service()
    if not svc:
        return []
    _ensure_tab(_TAB)
    try:
        result = svc.spreadsheets().values().get(
            spreadsheetId=_get_sheet_id(), range=f"{_TAB}!A2:F1000"
        ).execute()
        return result.get("values", [])
    except Exception:
        return []


def add_note(member: str, title: str, content: str, tags: str = "") -> bool:
    return _append_row([_today(), _now(), member, title, content, tags])


def list_notes(limit: int = 10) -> list[dict]:
    rows = _read_all()
    notes = []
    for r in reversed(rows):
        if len(r) >= 4:
            notes.append({
                "date": r[0] if len(r) > 0 else "",
                "time": r[1] if len(r) > 1 else "",
                "member": r[2] if len(r) > 2 else "",
                "title": r[3] if len(r) > 3 else "",
                "content": r[4] if len(r) > 4 else "",
                "tags": r[5] if len(r) > 5 else "",
            })
        if len(notes) >= limit:
            break
    return notes


def search_notes(keyword: str) -> list[dict]:
    rows = _read_all()
    results = []
    kw = keyword.lower()
    for r in reversed(rows):
        if len(r) >= 4:
            title = r[3] if len(r) > 3 else ""
            content = r[4] if len(r) > 4 else ""
            if kw in title.lower() or kw in content.lower():
                results.append({
                    "date": r[0] if len(r) > 0 else "",
                    "time": r[1] if len(r) > 1 else "",
                    "member": r[2] if len(r) > 2 else "",
                    "title": title,
                    "content": content,
                    "tags": r[5] if len(r) > 5 else "",
                })
    return results


def delete_note(title: str) -> bool:
    svc = _get_service()
    if not svc:
        return False
    rows = _read_all()
    for i, r in enumerate(rows, start=2):
        if len(r) > 3 and r[3] == title:
            try:
                meta = svc.spreadsheets().get(spreadsheetId=_get_sheet_id()).execute()
                sheet_id = None
                for s in meta.get("sheets", []):
                    if s["properties"]["title"] == _TAB:
                        sheet_id = s["properties"]["sheetId"]
                        break
                if sheet_id is None:
                    return False
                svc.spreadsheets().batchUpdate(
                    spreadsheetId=_get_sheet_id(),
                    body={"requests": [{"deleteDimension": {
                        "range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": i - 1, "endIndex": i}
                    }}]},
                ).execute()
                return True
            except Exception as e:
                print(f"[Notebook] Delete failed: {e}")
                return False
    return False


# ── webhook handlers ─────────────────────────────

def handle_notebook_command(reply_token: str, text: str, member: str, reply_fn) -> bool:
    """Handle notebook commands. Returns True if handled."""
    if text == "記事本":
        notes = list_notes(10)
        if not notes:
            reply_fn(reply_token, "📝 記事本還沒有內容\n用法：記事 標題 內容")
            return True
        lines = ["📝 記事本（最近10則）："]
        for n in notes:
            tags = f" [{n['tags']}]" if n.get("tags") else ""
            lines.append(f"• {n['date']} {n['title']}{tags}")
        lines.append("\n🔍 找記事 關鍵字\n🗑️ 刪除記事 標題")
        reply_fn(reply_token, "\n".join(lines))
        return True

    m = re.match(r"^(?:記事|筆記)\s+(.+)", text)
    if m:
        rest = m.group(1)
        parts = rest.split(None, 1)
        if len(parts) < 2:
            reply_fn(reply_token, "用法：記事 標題 內容")
            return True
        title, content = parts[0], parts[1]
        ok = add_note(member or "家人", title, content)
        reply_fn(reply_token, f"✅ 已新增記事「{title}」" if ok else "❌ 新增失敗")
        return True

    m = re.match(r"^(?:找記事|搜尋記事|記事搜尋)\s+(.+)", text)
    if m:
        kw = m.group(1)
        results = search_notes(kw)
        if not results:
            reply_fn(reply_token, f"🔍 找不到「{kw}」相關記事")
            return True
        lines = [f"🔍 「{kw}」搜尋結果："]
        for r in results[:10]:
            lines.append(f"• {r['date']} {r['title']} — {r['content'][:30]}...")
        reply_fn(reply_token, "\n".join(lines))
        return True

    m = re.match(r"^(?:刪除記事)\s+(.+)", text)
    if m:
        title = m.group(1)
        ok = delete_note(title)
        reply_fn(reply_token, f"🗑️ 已刪除「{title}」" if ok else f"❌ 找不到「{title}」")
        return True

    return False
