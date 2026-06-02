"""
睡前待辦提醒 — 21:00 CST
檢查明天待辦 + 今日逾期的最後催促（AI 嗆辣版）
"""

import os
import sys
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.path.dirname(__file__))
from sheets import get_todos
from api_helpers import call_ai
from line_push import push_text_to_group

TW_TZ = timezone(timedelta(hours=8))


def _ai_shame_list(todos: list[dict]) -> list[str]:
    """Ask AI to generate funny roast lines for each pending todo."""
    if not todos:
        return []
    items_text = "\n".join(f"{i+1}. {t['member']}｜{t['content']}" for i, t in enumerate(todos))
    prompt = (
        f"以下是家人沒做完的待辦事項，幫每個寫一句嗆人催促語，"
        f"要搞笑、誇張、有梗、帶 emoji，每句不超過 30 字，繁體中文。\n\n"
        f"{items_text}\n\n"
        f"格式：只回覆列表，每句一行，前面加「- 」，不要其他說明。"
    )
    result = call_ai(prompt)
    if result:
        shames = [line.lstrip("- ").strip() for line in result.strip().split("\n") if line.strip()]
        if len(shames) >= len(todos):
            return shames[:len(todos)]
    return ["快去做啦！💢"] * len(todos)


def main():
    todos = get_todos(only_pending=True)
    today = datetime.now(TW_TZ).strftime("%Y-%m-%d")
    tomorrow = (datetime.now(TW_TZ) + timedelta(days=1)).strftime("%Y-%m-%d")

    today_todos = [t for t in todos if t["date"] == today]
    overdue_todos = [t for t in todos if t["date"] < today]
    tomorrow_todos = [t for t in todos if t["date"] == tomorrow]

    lines = []
    all_shame_targets = overdue_todos + today_todos
    shame_lines = _ai_shame_list(all_shame_targets) if all_shame_targets else []

    # 今晚最後通牒（AI 嗆辣版）
    if overdue_todos:
        lines.append("🔥 逾期公審時間 🔥")
        for i, t in enumerate(overdue_todos):
            days_overdue = (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(t["date"], "%Y-%m-%d")).days
            if days_overdue == 1:
                day_str = "昨天就該做完了"
            else:
                day_str = f"逾期 {days_overdue} 天"
            shame = shame_lines[i] if i < len(shame_lines) else "快去做啦！💢"
            lines.append(f"  • {t['member']}｜{t['content']}（{day_str}）— {shame}")
        lines.append("\n以上人士，請自重 👮‍♂️")
        lines.append("")

    if today_todos:
        lines.append("⏰ 今天還沒完成的待辦：")
        offset = len(overdue_todos)
        for i, t in enumerate(today_todos):
            shame = shame_lines[offset + i] if (offset + i) < len(shame_lines) else "快去做啦！💢"
            lines.append(f"  • {t['member']}｜{t['content']} — {shame}")
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
