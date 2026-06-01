"""
每週一 00:05 CST — 結算上週罰款 + 發送本週家事清單
"""

import math
import os
from datetime import datetime, timezone, timedelta
from sheets import get_members, get_last_week_points, get_chores, add_fine, get_outstanding_fines, get_setting, set_setting
from line_push import push_text_to_group

TW_TZ = timezone(timedelta(hours=8))
POINTS_THRESHOLD = int(os.environ.get("POINTS_THRESHOLD", "5"))
FINE_PER_POINT = int(os.environ.get("FINE_PER_POINT", "50"))


def main():
    today = datetime.now(TW_TZ).strftime("%Y-%m-%d")
    if get_setting("weekly_penalty_last_run") == today:
        print(f"Weekly penalty already ran on {today}, skipping.")
        return

    members = get_members()
    pts = get_last_week_points()

    # 上週週次標籤
    today = datetime.now(TW_TZ).date()
    this_monday = today - timedelta(days=today.weekday())
    last_monday = this_monday - timedelta(days=7)
    last_sunday = this_monday - timedelta(days=1)
    week_label = f"{last_monday.strftime('%m/%d')}－{last_sunday.strftime('%m/%d')}"

    lines = [f"💰 上週（{week_label}）家事結算\n"]

    fined = []
    ok = []
    for m in members:
        p = pts.get(m, 0.0)
        floored = math.floor(p)
        if floored < POINTS_THRESHOLD:
            shortfall = POINTS_THRESHOLD - floored
            fine = shortfall * FINE_PER_POINT
            add_fine(m, last_monday.strftime("%Y-%m-%d"), p, fine)
            fined.append((m, p, shortfall, fine))
        else:
            ok.append((m, p))

    if fined:
        for m, p, short, fine in fined:
            p_str = f"{p:.1f}"
            lines.append(f"❌ {m}：{p_str} 點，差 {short} 點 → 罰款 {fine} 元")
    if ok:
        for m, p in ok:
            p_str = f"{p:.1f}"
            lines.append(f"✅ {m}：{p_str} 點，達標")

    if fined:
        lines.append("\n💡 實體投幣後傳「繳罰款 金額」給機器人登記")

    # 累積欠款
    all_balances = get_outstanding_fines()
    if all_balances:
        lines.append("\n📒 小本本累積欠款：")
        for m, total in all_balances.items():
            if total > 0:
                lines.append(f"  {m}：欠 {total} 元")

    # 本週家事清單
    chores = get_chores()
    lines.append("\n\n🗓️ 新的一週開始！本週家事清單：")
    for c in chores[:10]:
        lines.append(f"  • {c['name']}（{c['points']}點）")
    lines.append(f"\n目標：每週 {POINTS_THRESHOLD} 點，加油 💪")

    push_text_to_group("\n".join(lines))
    set_setting("weekly_penalty_last_run", today)
    print("Weekly penalty sent.")


main()
