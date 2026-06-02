"""
睡前待辦提醒 — 21:00 CST
檢查明天待辦 + 今日逾期的最後催促（嗆辣版）
"""

import os
import sys
import random
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.path.dirname(__file__))
from sheets import get_todos
from line_push import push_text_to_group

TW_TZ = timezone(timedelta(hours=8))

_SHAME_LINES = [
    "還在滑手機？這個先做啦！📱💢",
    "今天結束了欸！！時間管理大師？🙃",
    "再拖下去就變成歷史古蹟了 🏛️",
    "這件事的優先級是：現在立刻馬上！⏰",
    "你是打算等到明年再做嗎？🎆",
    "這個待辦已經可以申請世界遺產了 🌍",
    "再不做，它就要過生日了 🎂",
    "你的待辦在哭，你看不到嗎？😭",
]


def _shame() -> str:
    return random.choice(_SHAME_LINES)


def main():
    todos = get_todos(only_pending=True)
    today = datetime.now(TW_TZ).strftime("%Y-%m-%d")
    tomorrow = (datetime.now(TW_TZ) + timedelta(days=1)).strftime("%Y-%m-%d")

    today_todos = [t for t in todos if t["date"] == today]
    overdue_todos = [t for t in todos if t["date"] < today]
    tomorrow_todos = [t for t in todos if t["date"] == tomorrow]

    lines = []

    # 今晚最後通牒（嗆辣版）
    if overdue_todos:
        lines.append("🔥 逾期公審時間 🔥")
        for t in overdue_todos:
            days_overdue = (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(t["date"], "%Y-%m-%d")).days
            if days_overdue == 1:
                day_str = "昨天就該做完了"
            else:
                day_str = f"逾期 {days_overdue} 天"
            lines.append(f"  • {t['member']}｜{t['content']}（{day_str}）— {_shame()}")
        lines.append("\n以上人士，請自重 👮‍♂️")
        lines.append("")

    if today_todos:
        lines.append("⏰ 今天還沒完成的待辦：")
        for t in today_todos:
            lines.append(f"  • {t['member']}｜{t['content']} — {_shame()}")
        lines.append("\n今天快結束了，沒做完的人自己看著辦 😤")
        lines.append("")

    # 明天預告（溫柔一點）
    if tomorrow_todos:
        lines.append("📅 明天待辦預告：")
        for t in tomorrow_todos:
            lines.append(f"  • {t['member']}｜{t['content']}")
        lines.append("\n早點睡，明天又是美好的一天 💪")
        lines.append("")

    if not lines:
        lines.append("🌙 今晚沒有待辦，可以安心睡覺啦～晚安！😴")

    push_text_to_group("\n".join(lines))
    print("Evening todo reminder sent.")


main()
