"""
清理 點數記錄 tab 中成員為「家人」的資料
使用環境變數：GOOGLE_CREDENTIALS_JSON 或個別 GOOGLE_CLIENT_ID/SECRET/REFRESH_TOKEN
以及 FAMILY_SHEET_ID
"""
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))
from sheets import _get_service, _get_sheet_id


def main():
    svc = _get_service()
    sid = _get_sheet_id()

    rows = svc.spreadsheets().values().get(
        spreadsheetId=sid, range="點數記錄!A2:E500"
    ).execute().get("values", [])

    print(f"總共 {len(rows)} 筆記錄")
    jia_ren = [r for r in rows if len(r) > 1 and r[1].strip() == "家人"]
    keep = [r for r in rows if not (len(r) > 1 and r[1].strip() == "家人")]

    print(f"家人記錄：{len(jia_ren)} 筆")
    for r in jia_ren:
        print(f"  {r}")

    if not jia_ren:
        print("沒有家人記錄，不需要清理")
        return

    confirm = input("\n確認刪除？(y/n): ")
    if confirm.lower() != "y":
        print("取消")
        return

    svc.spreadsheets().values().clear(spreadsheetId=sid, range="點數記錄!A2:E500").execute()
    if keep:
        svc.spreadsheets().values().update(
            spreadsheetId=sid, range="點數記錄!A2",
            valueInputOption="USER_ENTERED", body={"values": keep},
        ).execute()
    print(f"完成！刪除了 {len(jia_ren)} 筆")


main()
