"""
睡前待辦提醒 — 21:00 CST
檢查明天待辦 + 今日逾期的最後催促
"""

import os
import sys
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.path.dirname(__file__))
from sheets import get_todos
from line_push import push_text_to_group

TW_TZ = timezone(timedelta(hours=8))


def main():
    todos = get_todos(only_pending=True)
    today = datetime.now(TW_TZ).strftime("%Y-%m-%d")
    tomorrow = (datetime.now(TW_TZ) + timedelta(days=1)).strftime("%Y-%m-%d")

    today_todos = [t for t in todos if t["date"] == today]
    overdue_todos = [t for t in todos if t["date"] < today]
    tomorrow_todos = [t for t in todos if t["date"] == tomorrow]

    lines = []

    # 今晚最後通牒
    if overdue_todos:
        lines.append("🌙 睡前催更 🔥")
        for t in overdue_todos:
            days_overdue = (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(t["date"], "%Y-%m-%d")).days
            day_str = f"{days_overdue} 天" if days_overdue > 1 else "今天"
            lines.append(f"  • {t['member']}｜{t['content']}（已逾期 {day_str}）")
        lines.append("\n這些任務已經逾期了，請盡快完成！💢")
        lines.append("")

    if today_todos:
        lines.append("⏰ 今天還沒完成的待辦：")
        for t in today_todos:
            lines.append(f"  • {t['member']}｜{t['content']}")
        lines.append("\n今天快結束了，趕緊做完可以安心睡覺 😴")
        lines.append("")

    # 明天預告
    if tomorrow_todos:
        lines.append("📅 明天待辦預告：")
        for t in tomorrow_todos:
            lines.append(f"  • {t['member']}｜{t['content']}")
        lines.append("\n明天也要加油！💪")
        lines.append("")

    if not lines:
        # 什麼都沒有就發個晚安
        lines.append("🌙 今晚沒有待辦，可以安心睡覺啦～晚安！😴")

    push_text_to_group("\n".join(lines))
    print("Evening todo reminder sent.")


main()
