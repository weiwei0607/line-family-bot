"""修復 2026-06-05 媽媽「整理廚房 1」被誤記為收拾的問題。

用法：
    cd ~/development/line-family-bot
    python scripts/fix_records.py

需要環境變數：FAMILY_SHEET_ID, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone

TW_TZ = timezone(timedelta(hours=8))


def _today_str():
    return datetime.now(TW_TZ).strftime("%Y-%m-%d")


def _now_str():
    return datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M")


def main():
    from scripts.sheets import _get_service, _get_sheet_id, _read

    svc = _get_service()
    sid = _get_sheet_id()
    today = _today_str()

    # ── 1) 找出「收拾紀錄」中要刪除的那行 ──
    tidy_rows = _read("收拾紀錄", "A2:E1000")
    target_row = None  # 1-based row number in sheet

    for i, row in enumerate(tidy_rows, start=2):  # A2 → row 2
        if len(row) < 5:
            continue
        date_str, time_str, member, area, content = row[0], row[1] if len(row) > 1 else "", row[2] if len(row) > 2 else "", row[3] if len(row) > 3 else "", row[4] if len(row) > 4 else ""
        if date_str == today and member == "媽媽" and "廚房" in content:
            target_row = i
            print(f"找到收拾紀錄：row {i} → {date_str} {time_str} {member} {area} {content}")
            break

    if not target_row:
        print("沒有找到媽媽今天『廚房』相關的收拾紀錄，可能已經刪除了？")
    else:
        # 取得「收拾紀錄」的 sheetId
        meta = svc.spreadsheets().get(spreadsheetId=sid).execute()
        tidy_sheet_id = None
        for s in meta.get("sheets", []):
            if s["properties"]["title"] == "收拾紀錄":
                tidy_sheet_id = s["properties"]["sheetId"]
                break

        if tidy_sheet_id is None:
            print("找不到『收拾紀錄』工作表")
            sys.exit(1)

        # 刪除那行（deleteDimension 用 0-based index）
        row_index = target_row - 1
        svc.spreadsheets().batchUpdate(
            spreadsheetId=sid,
            body={
                "requests": [{
                    "deleteDimension": {
                        "range": {
                            "sheetId": tidy_sheet_id,
                            "dimension": "ROWS",
                            "startIndex": row_index,
                            "endIndex": row_index + 1,
                        }
                    }
                }]
            },
        ).execute()
        print(f"✅ 已刪除收拾紀錄 row {target_row}")

    # ── 2) 補上家事點數記錄 ──
    now = _now_str()
    svc.spreadsheets().values().append(
        spreadsheetId=sid,
        range="點數記錄!A1",
        valueInputOption="USER_ENTERED",
        body={"values": [[today, "媽媽", "整理廚房", 1, now]]},
    ).execute()
    print("✅ 已補上點數記錄：媽媽 整理廚房 +1")


if __name__ == "__main__":
    main()
