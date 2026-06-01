"""Batch chore logging handler (multi-line input)."""

import re
from line_push import reply_text as reply
from sheets import (
    get_members, get_chores, get_member_weekly_chore_points,
    batch_log_points, format_weekly_summary, WEEKLY_CAPS,
)


def handle_batch_log(reply_token: str, member: str, text: str) -> bool:
    """批量登錄：第一行「完成」，後續每行一個家事"""
    lines = [l.strip() for l in text.strip().splitlines()]
    if len(lines) < 2:
        return False

    first = lines[0]
    if first not in ["完成", "完成了"] and not re.match(r'^\d+[/／]\d+\s*完成', first):
        return False

    chore_lines = lines[1:]

    # 最後一行只有匹配到已登記成員才視為名字
    members_list = get_members()
    who = member or ""
    last = chore_lines[-1] if chore_lines else ""
    if last and not re.search(r'\d', last):
        matched = next((m for m in members_list if m in last or last in m), None)
        if matched:
            who = matched
            chore_lines = chore_lines[:-1]

    # 解析家事行
    chore_pattern = re.compile(r'^(.+?)(\d+\.?\d*)$')
    chores_sheet = None
    chores: list[tuple[str, float]] = []
    for line in chore_lines:
        if not line:
            continue
        m = chore_pattern.match(line)
        if m:
            chores.append((m.group(1).strip(), float(m.group(2))))
        else:
            if chores_sheet is None:
                chores_sheet = get_chores()
            matched_chore = next(
                (c for c in chores_sheet if line in c["name"] or c["name"] in line),
                None,
            )
            pts = matched_chore["points"] if matched_chore else 1.0
            name = matched_chore["name"] if matched_chore else line
            chores.append((name, pts))

    if not chores:
        reply(reply_token, "沒有找到任何家事，請確認格式：\n完成\n家事名稱\n家事名稱")
        return True

    # 上限檢查（跳過超過上限的項目）
    who = who or member or "家人"
    valid_chores: list[tuple[str, float]] = []
    capped_names: list[str] = []
    for name, pts in chores:
        cap = WEEKLY_CAPS.get(name)
        if cap is not None:
            already = get_member_weekly_chore_points(who, name)
            remaining = cap - already
            if remaining <= 0:
                capped_names.append(name)
                continue
            pts = min(pts, remaining)
        valid_chores.append((name, pts))

    if not valid_chores:
        cap_str = "、".join(capped_names)
        reply(reply_token, f"⚠️ {who} 本週「{cap_str}」已達點數上限，沒有新增記錄。")
        return True

    try:
        batch_log_points(who, valid_chores)
        summary = format_weekly_summary()
    except Exception as e:
        reply(reply_token, f"記錄失敗：{e}")
        return True

    total = sum(p for _, p in valid_chores)
    total_str = f"{total:.2f}".rstrip('0').rstrip('.')
    lines_out = [f"✅ {name} +{f'{pts:.2f}'.rstrip('0').rstrip('.')}" for name, pts in valid_chores]

    msg = f"📋 {who} 的家事記錄\n" + "\n".join(lines_out) + f"\n\n共 +{total_str} 點 🎉"
    if capped_names:
        msg += f"\n⚠️ 已達上限略過：{'、'.join(capped_names)}"
    msg += f"\n\n{summary}"
    reply(reply_token, msg)
    return True
