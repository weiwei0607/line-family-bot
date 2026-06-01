"""
每日家事提醒 — 08:00 CST
提醒點數不足的人做家事 + 列出今日待完成家事
"""

import os
import sys
sys.path.insert(0, os.path.dirname(__file__))
from sheets import get_members, get_chores, get_weekly_points
from api_helpers import format_weather_block
from line_push import push_text_to_group

POINTS_THRESHOLD = int(os.environ.get("POINTS_THRESHOLD", "5"))


def main():
    members = get_members()
    pts = get_weekly_points()
    chores = get_chores()

    # 點數不足的人
    low_pts = [m for m in members if pts.get(m, 0) < POINTS_THRESHOLD]

    lines = ["☀️ 早安！家管助理日報\n"]
    lines.append(format_weather_block())
    lines.append("")

    # 待完成家事
    if chores:
        lines.append(f"📋 今日待完成家事（共 {len(chores)} 項）：")
        for c in chores[:8]:
            lines.append(f"  • {c['name']}（{c['points']}點）")
    else:
        lines.append("🎉 今日家事全部完成！大家辛苦了！")

    lines.append("")

    # 點數提醒
    if low_pts:
        lines.append(f"⚠️ 本週點數還不夠的成員：")
        for m in low_pts:
            p = pts.get(m, 0)
            lines.append(f"  {m}：目前 {p} 點（目標 {POINTS_THRESHOLD} 點）")
        lines.append("\n快去完成家事累積點數吧！💪")
    else:
        lines.append("✅ 大家本週點數都達標了，棒棒！🎉")

    lines.append("\n輸入「家事清單」查看待完成家事")
    push_text_to_group("\n".join(lines))
    print("Daily reminder sent.")


main()
