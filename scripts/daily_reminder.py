"""
每日家事提醒 — 08:00 CST
提醒點數不足的人做家事 + 列出今日待完成家事 + 待辦提醒/逾期公審
"""

import os
import sys
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.path.dirname(__file__))
from sheets import get_members, get_chores, get_weekly_points, get_todos
from api_helpers import format_weather_block
from line_push import push_text_to_group

POINTS_THRESHOLD = int(os.environ.get("POINTS_THRESHOLD", "5"))
TW_TZ = timezone(timedelta(hours=8))


def main():
    members = get_members()
    pts = get_weekly_points()
    chores = get_chores()
    todos = get_todos(only_pending=True)

    today = datetime.now(TW_TZ).strftime("%Y-%m-%d")
    tomorrow = (datetime.now(TW_TZ) + timedelta(days=1)).strftime("%Y-%m-%d")

    # 分類待辦
    today_todos = [t for t in todos if t["date"] == today]
    overdue_todos = [t for t in todos if t["date"] < today]
    tomorrow_todos = [t for t in todos if t["date"] == tomorrow]

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

    # 待辦提醒（早上溫柔版）
    if today_todos or overdue_todos:
        if today_todos:
            lines.append("📅 今天待辦：")
            for t in today_todos:
                by = f"（{t['created_by']} 記的）" if t.get('created_by') and t['created_by'] != t['member'] else ""
                lines.append(f"  • {t['member']}｜{t['content']}{by}")
            lines.append("")

        if overdue_todos:
            lines.append("⏰ 已經逾期，但今天還有機會補上 💪")
            for t in overdue_todos:
                days_overdue = (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(t["date"], "%Y-%m-%d")).days
                if days_overdue == 1:
                    day_str = "昨天到期"
                else:
                    day_str = f"逾期 {days_overdue} 天"
                lines.append(f"  • {t['member']}｜{t['content']}（{day_str}）")
            lines.append("\n沒關係的，慢慢來，今天記得處理就好 🥺✨")
            lines.append("")
    else:
        lines.append("✅ 沒有待辦事項，太棒了！")
        lines.append("")

    # 明天的待辦預告
    if tomorrow_todos:
        lines.append("📢 明天提醒：")
        for t in tomorrow_todos:
            lines.append(f"  • {t['member']}｜{t['content']}")
        lines.append("")

    # 點數提醒
    low_pts = [m for m in members if pts.get(m, 0) < POINTS_THRESHOLD]
    if low_pts:
        lines.append(f"⚠️ 本週點數還不夠的成員：")
        for m in low_pts:
            p = pts.get(m, 0)
            lines.append(f"  {m}：目前 {p} 點（目標 {POINTS_THRESHOLD} 點）")
        lines.append("\n快去完成家事累積點數吧！💪")
    else:
        lines.append("✅ 大家本週點數都達標了，棒棒！🎉")

    lines.append("\n輸入「家事清單」查看待完成家事｜「待辦清單」查看所有待辦")
    push_text_to_group("\n".join(lines))
    print("Daily reminder sent.")


main()
