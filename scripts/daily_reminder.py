"""
每日家事提醒 — 08:00 CST
提醒點數不足的人做家事 + 列出今日待完成家事 + 待辦提醒/逾期公審
"""

import os
import sys
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.path.dirname(__file__))
from sheets import get_members, get_chores, get_weekly_points, get_todos
from api_helpers import format_weather_block, call_ai
from line_push import push_text_to_group


def _ai_gentle_nudge(todos: list[dict]) -> str:
    """Ask AI to write a warm morning encouragement based on pending todos."""
    if not todos:
        return "✨ 今天沒有待辦，盡情享受美好的一天吧！"
    items_text = "\n".join(f"{i+1}. {t['member']}｜{t['content']}" for i, t in enumerate(todos))
    prompt = (
        f"早安！以下是家人今天的待辦事項，請幫我寫一段溫柔可愛的鼓勵語，"
        f"提醒大家完成，語氣溫暖、帶 emoji、像家人一樣關心，繁體中文，50 字以內。\n\n"
        f"{items_text}\n\n"
        f"只回覆鼓勵語本身，不要加標題或說明。"
    )
    result = call_ai(prompt)
    return result or "今天也要加油喔！💪✨"

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

    # 待辦提醒（早上 AI 溫柔版）
    all_todos = today_todos + overdue_todos
    if all_todos:
        if today_todos:
            lines.append("📅 今天待辦：")
            for t in today_todos:
                by = f"（{t['created_by']} 記的）" if t.get('created_by') and t['created_by'] != t['member'] else ""
                lines.append(f"  • {t['member']}｜{t['content']}{by}")
            lines.append("")

        if overdue_todos:
            lines.append("⏰ 已經逾期，但今天還有機會補上：")
            for t in overdue_todos:
                days_overdue = (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(t["date"], "%Y-%m-%d")).days
                if days_overdue == 1:
                    day_str = "昨天到期"
                else:
                    day_str = f"逾期 {days_overdue} 天"
                lines.append(f"  • {t['member']}｜{t['content']}（{day_str}）")
            lines.append("")

        # AI 溫柔鼓勵語
        nudge = _ai_gentle_nudge(all_todos)
        lines.append(nudge)
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
