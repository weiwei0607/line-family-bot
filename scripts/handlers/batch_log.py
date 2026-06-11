"""Batch chore logging handler (multi-line input)."""

import re
from line_push import reply_text as reply
from sheets import (
    get_members, get_chores, get_member_weekly_chore_points,
    batch_log_points, format_weekly_summary, WEEKLY_CAPS,
    add_tidy_log, _detect_area,
)


def handle_batch_log(reply_token: str, member: str, text: str) -> bool:
    """批量登錄：第一行「完成」，後續每行一個家事或收拾內容"""
    lines = [l.strip() for l in text.strip().splitlines()]
    if len(lines) < 2:
        return False

    first = lines[0]
    if first not in ["完成", "完成了"] and not re.match(r'^\d+[/／]\d+\s*完成', first):
        return False

    chore_lines = lines[1:]

    # 最後一行只有匹配到已登記成員才視為名字
    members_list = get_members()
    sender = member or ""
    who = sender or ""
    last = chore_lines[-1] if chore_lines else ""
    if last and not re.search(r'\d', last):
        matched = next((m for m in members_list if m in last or last in m), None)
        if matched:
            who = matched
            chore_lines = chore_lines[:-1]

    who = who or sender or "家人"

    # 解析家事行，智能分流：家事 / 收拾
    chore_pattern = re.compile(r'^(.+?)(\d+\.?\d*)$')
    chores_sheet = None
    chores: list[tuple[str, float]] = []
    tidy_items: list[tuple[str, str]] = []  # (area, content)
    tidy_rejected: list[str] = []  # 因「不能自己記」被拒絕的收拾項目
    errors: list[str] = []

    # 檢查是否為自己記錄收拾（收拾不能自己紀錄，需由他人代為）
    self_tidy_blocked = bool(sender and sender == who and sender in members_list)

    for line in chore_lines:
        if not line:
            continue

        # 1) 先嘗試匹配家事（含自定分數）
        m = chore_pattern.match(line)
        if m:
            name = m.group(1).strip()
            pts = float(m.group(2))
            chores.append((name, pts))
            continue

        if chores_sheet is None:
            chores_sheet = get_chores()
        matched_chore = next(
            (c for c in chores_sheet if line in c["name"] or c["name"] in line),
            None,
        )

        if matched_chore:
            # 匹配到已知家事 → 記家事
            chores.append((matched_chore["name"], matched_chore["points"]))
            continue

        # 2) 家事沒匹配到，檢查是否以「收拾/整理」開頭 → 走 tidy
        m_tidy = re.match(r'^(收拾|整理)\s*(.*)', line)
        if m_tidy:
            content = m_tidy.group(2).strip()
            if not content:
                # 「收拾」兩個字單獨一行 → 只是標記，不記錄
                continue
            area = _detect_area(content)
            if area != "未分類":
                if self_tidy_blocked:
                    tidy_rejected.append(f"• {content}（{area}）")
                else:
                    tidy_items.append((area, content))
            else:
                errors.append(f"• {line}（請標註「自己」或「公共」，例如：自己 {line}）")
            continue

        # 3) 也不是 tidy，檢查 _detect_area 是否能識別區域 → 走 tidy
        area = _detect_area(line)
        if area != "未分類":
            if self_tidy_blocked:
                tidy_rejected.append(f"• {line}（{area}）")
            else:
                tidy_items.append((area, line))
        else:
            # 家事也找不到、區域也分不出 → 請使用者講清楚
            errors.append(f"• {line}（請標註「自己」或「公共」，例如：自己 {line}）")

    # 記錄收拾（只記非自己幫自己記的）
    for area, content in tidy_items:
        add_tidy_log(who, area, content)

    # 上限檢查（跳過超過上限的項目）
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

    # 組合回覆訊息
    parts: list[str] = []

    # 收拾紀錄區
    if tidy_items:
        tidy_lines = []
        for area, content in tidy_items:
            emoji = "🧹" if area == "自己" else "🧽" if area == "公共" else "🧺"
            tidy_lines.append(f"{emoji} {content}（{area}）")
        parts.append(f"🧹 {who} 的收拾紀錄\n" + "\n".join(tidy_lines))

    # 家事記錄區
    if valid_chores:
        try:
            batch_log_points(who, valid_chores)
            summary = format_weekly_summary()
        except Exception as e:
            reply(reply_token, f"記錄失敗：{e}")
            return True

        total = sum(p for _, p in valid_chores)
        total_str = f"{total:.2f}".rstrip('0').rstrip('.')
        chore_lines_out = [f"✅ {name} +{f'{pts:.2f}'.rstrip('0').rstrip('.')}" for name, pts in valid_chores]
        parts.append(f"📋 {who} 的家事記錄\n" + "\n".join(chore_lines_out) + f"\n\n共 +{total_str} 點 🎉")

        if capped_names:
            parts[-1] += f"\n⚠️ 已達上限略過：{'、'.join(capped_names)}"
        parts.append(summary)

    # 自己不能幫自己記收拾的提示
    if self_tidy_blocked and tidy_rejected:
        parts.append("🚫 以下收拾無法自己紀錄，請由其他家人代為記錄\n" + "\n".join(tidy_rejected))

    # 無法分類的項目
    if errors:
        parts.append("❓ 以下項目分不出區域，請標註「自己」或「公共」\n" + "\n".join(errors))

    # 都沒有
    if not parts:
        reply(reply_token, "沒有找到任何家事或收拾內容，請確認格式：\n完成\n家事名稱\n收拾 客廳")
        return True

    msg = "\n\n".join(parts)
    reply(reply_token, msg)
    return True
