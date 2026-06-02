"""
Todo / reminder management handlers for family bot.
"""

import re
from datetime import datetime, timedelta
from sheets import add_todo, get_todos, complete_todo_by_content, TW_TZ

_CN_NUM = {
    '零': 0, '一': 1, '二': 2, '三': 3, '四': 4,
    '五': 5, '六': 6, '七': 7, '八': 8, '九': 9,
    '十': 10,
}

def _cn_to_int(s: str) -> int | None:
    """Convert simple Chinese number (零~二十九) to int."""
    if s.isdigit():
        return int(s)
    if s in _CN_NUM:
        return _CN_NUM[s]
    if s.startswith('十'):
        return 10 + (_CN_NUM.get(s[1:], 0) if len(s) > 1 else 0)
    if len(s) == 2 and s[1] == '十':
        return _CN_NUM.get(s[0], 0) * 10
    if len(s) == 3 and s[1] == '十':
        return _CN_NUM.get(s[0], 0) * 10 + _CN_NUM.get(s[2], 0)
    return None


def _extract_time(content: str) -> str | None:
    """Extract HH:MM from Chinese time expression in content string."""
    m = re.search(
        r'(今晚|今天晚上|晚上|早上|上午|下午|中午|凌晨|傍晚)'
        r'([零一二三四五六七八九十\d]+)點'
        r'(半|([零一二三四五六七八九十\d]+)分?)?',
        content
    )
    if not m:
        return None
    prefix, hour_s, suffix, minute_s = m.group(1), m.group(2), m.group(3), m.group(4)
    hour = _cn_to_int(hour_s)
    if hour is None:
        return None
    if suffix == '半':
        minute = 30
    elif minute_s:
        minute = _cn_to_int(minute_s) or 0
    else:
        minute = 0
    # Apply AM/PM offset
    if prefix in ('晚上', '今晚', '今天晚上', '傍晚') and hour < 12:
        hour += 12
    elif prefix == '下午' and hour < 12:
        hour += 12
    elif prefix == '中午':
        hour = 12
    elif prefix == '凌晨' and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return f"{hour:02d}:{minute:02d}"


def _parse_reminder_date(s: str) -> str | None:
    today = datetime.now(TW_TZ).date()
    if s in ["今天"]:
        return today.strftime("%Y-%m-%d")
    if s in ["明天", "明日"]:
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")
    if s in ["後天"]:
        return (today + timedelta(days=2)).strftime("%Y-%m-%d")
    m = re.match(r'^(\d{1,2})[/月](\d{1,2})日?$', s)
    if m:
        try:
            from datetime import date as _d
            mo, dy = int(m.group(1)), int(m.group(2))
            t = _d(today.year, mo, dy)
            if t < today:
                t = _d(today.year + 1, mo, dy)
            return t.strftime("%Y-%m-%d")
        except ValueError:
            return None
    return None


_TIME_EXPR = r'(?:今晚|今天晚上|晚上|早上|上午|下午|中午|凌晨|傍晚)(?:\d+|[零一二三四五六七八九十百]+)點\S*'


def _extract_reminder(text: str) -> tuple | None:
    """Parse reminder text, supporting with or without spaces."""
    # Pattern 1: 提醒我 明天 交報告 / 提醒我明天交報告
    m = re.match(r'^提醒我\s*(今天|明天|後天|明日)\s*(.*)', text)
    if m:
        return (None, m.group(1), m.group(2).strip())
    m = re.match(r'^提醒我\s*(\d{1,2}[/月]\d{1,2}日?)\s*(.*)', text)
    if m:
        return (None, m.group(1), m.group(2).strip())
    # Pattern 1b: 提醒我 晚上九點半 做事 → 今天
    m = re.match(rf'^提醒我\s*({_TIME_EXPR})\s*(.*)', text)
    if m:
        content = f"{m.group(1)} {m.group(2)}".strip()
        return (None, "今天", content)
    # Pattern 2: 提醒 爸爸 明天 交報告 / 提醒爸爸明天交報告
    m = re.match(r'^提醒\s*(\S+?)\s*(今天|明天|後天|明日)\s*(.*)', text)
    if m:
        return (m.group(1), m.group(2), m.group(3).strip())
    m = re.match(r'^提醒\s*(\S+?)\s*(\d{1,2}[/月]\d{1,2}日?)\s*(.*)', text)
    if m:
        return (m.group(1), m.group(2), m.group(3).strip())
    # Pattern 2b: 提醒 爸爸 晚上九點半 做事 → 今天
    m = re.match(rf'^提醒\s*(\S+?)\s*({_TIME_EXPR})\s*(.*)', text)
    if m:
        content = f"{m.group(2)} {m.group(3)}".strip()
        return (m.group(1), "今天", content)
    # Pattern 3: 提醒我 任何內容 → 今天（無日期也沒關係）
    m = re.match(r'^提醒我\s*(.*)', text)
    if m:
        return (None, "今天", m.group(1).strip())
    return None


def handle_add_todo(member: str, text: str) -> str:
    parsed = _extract_reminder(text)
    if not parsed:
        return "格式：提醒 [人名] [日期] [事項]\n或：提醒我 明天 要做XXX\n日期支援：今天/明天/後天/6/5"
    target, date_s, content = parsed
    if target is None:
        target = member or "你"
    if not content.strip():
        return "請加上提醒內容！\n例：提醒我明天 交報告"

    date_str = _parse_reminder_date(date_s)
    if not date_str:
        return f"看不懂日期「{date_s}」\n支援：今天/明天/後天/6月5日/6/5"

    time_str = _extract_time(content) or ""
    ok = add_todo(target, date_str, content, member or "", time_str=time_str)
    if not ok:
        return "記錄失敗，等一下再試 😢"
    date_display = date_str[5:].replace("-", "/")
    by_str = f"（{member} 幫你記的）" if target != member and member else ""
    time_note = f"（⏰ {time_str} 到時提醒）" if time_str else ""
    return f"✅ 已幫 {target} 記下！\n📅 {date_display}：{content}{by_str}{time_note}\n前一天晚上和當天都會提醒 🔔"


def handle_view_todos() -> str:
    todos = get_todos(only_pending=True)
    if not todos:
        return "🎉 目前沒有待辦事項！"
    today = datetime.now(TW_TZ).strftime("%Y-%m-%d")
    lines = ["📋 待辦事項：\n"]
    for t in sorted(todos, key=lambda x: x["date"]):
        date_display = t["date"][5:].replace("-", "/")
        overdue = " ⚠️ 逾期" if t["date"] < today else ""
        by = f"（{t['created_by']} 記的）" if t.get('created_by') and t['created_by'] != t['member'] else ""
        lines.append(f"• {t['member']}｜{date_display} {t['content']}{overdue}{by}")
    return "\n".join(lines)


def handle_complete_todo(member: str, text: str) -> str | None:
    content = re.sub(r'^完成待辦\s*', '', text).strip()
    if not content:
        return "請加上要完成的待辦內容！\n例：完成待辦 站起來走走"
    result = complete_todo_by_content(member, content)
    if result:
        return f"✅ 完成！「{result['content']}」從待辦清單移除 🎉"
    return f"找不到「{content}」在你的待辦裡"
