"""
每週總結 — 週日 23:59 CST
發送本週點數統計，點數下週自動從頭計算（依日期 >= 週一 filter）
"""

import os
from datetime import datetime, timezone, timedelta
from sheets import get_members, get_weekly_points, get_declutter_list, get_weekly_declutter_stats, get_setting, set_setting
from line_push import push_text_to_group

POINTS_THRESHOLD = int(os.environ.get("POINTS_THRESHOLD", "5"))
TW_TZ = timezone(timedelta(hours=8))


def main():
    today = datetime.now(TW_TZ).strftime("%Y-%m-%d")
    if get_setting("weekly_reset_last_run") == today:
        print(f"Weekly reset already ran on {today}, skipping.")
        return

    members = get_members()
    pts = get_weekly_points()

    sorted_members = sorted(members, key=lambda m: pts.get(m, 0), reverse=True)

    medals = ["🥇", "🥈", "🥉"]
    lines = ["🗓️ 本週家事點數總結！\n"]
    for i, m in enumerate(sorted_members):
        p = pts.get(m, 0)
        p_str = f"{p:.2f}".rstrip('0').rstrip('.')
        medal = medals[i] if i < 3 else "  "
        status = "✅ 達標" if p >= POINTS_THRESHOLD else "❌ 未達標"
        lines.append(f"{medal} {m}：{p_str} 點 {status}")

    lines.append(f"\n（每週目標：{POINTS_THRESHOLD} 點）")
    lines.append("新的一週從明天開始，大家繼續加油 💪")

    # 斷捨離週賽
    declutter_stats = get_weekly_declutter_stats()
    if declutter_stats:
        sorted_d = sorted(declutter_stats.items(), key=lambda x: (x[1]["count"], x[1]["income"]), reverse=True)
        lines.append("\n\n🗑️ 本週斷捨離競賽：")
        d_medals = ["🥇", "🥈", "🥉"]
        for i, (m, s) in enumerate(sorted_d):
            medal = d_medals[i] if i < 3 else "  "
            income_str = f"，賣出 {s['income']} 元" if s["income"] > 0 else ""
            lines.append(f"{medal} {m}：清了 {s['count']} 項{income_str}")

    # 斷捨離待定提醒
    pending = get_declutter_list(only_pending=True)
    if pending:
        lines.append(f"\n🗂️ 待定區還有 {len(pending)} 項，趁週末清一清！")
        for it in pending[:5]:
            lines.append(f"  • {it['name']}")
        if len(pending) > 5:
            lines.append(f"  ...還有 {len(pending)-5} 項")

    push_text_to_group("\n".join(lines))
    set_setting("weekly_reset_last_run", today)
    print("Weekly summary sent.")


main()
