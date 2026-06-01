"""Admin / identity / tidy-correction handlers."""

import re
from line_push import reply_text as reply
from handlers.member_cache import set_member
from sheets import get_members, bg, register_member, rename_latest_tidy_member


def handle_admin(reply_token: str, source, text: str) -> bool:
    """管理指令"""
    if text in ["群組id", "群組ID", "groupid", "群id"]:
        gid = getattr(source, "group_id", None) or getattr(source, "room_id", None) or "不是群組訊息"
        reply(reply_token, f"群組 ID：{gid}")
        return True

    m = re.match(r"^(?:我是|叫我|我叫)\s*(.+)", text)
    if m:
        name = m.group(1).strip()
        user_id = getattr(source, "user_id", "")
        approved = get_members()
        if name not in approved:
            names_str = "、".join(approved) if approved else "（尚未設定成員）"
            reply(reply_token, f"「{name}」不在成員名單裡喔！\n"
                               f"目前成員：{names_str}\n"
                               f"請用正確的家人稱呼 😊")
            return True
        if user_id and name:
            bg(register_member, user_id, name)
            set_member(user_id, name)
            reply(reply_token, f"好的！以後叫你「{name}」😊\n"
                               f"完成家事時傳「完成 家事名稱」就會記在你名下囉")
        return True

    # ── 修正收拾紀錄成員名稱 ──
    m_rename = re.match(r"^修正\s*(.+?)\s*為\s*(.+)$", text)
    if m_rename:
        old_name = m_rename.group(1).strip()
        new_name = m_rename.group(2).strip()
        changed = rename_latest_tidy_member(old_name, new_name)
        if not changed:
            reply(reply_token, f"找不到「{old_name}」的收拾紀錄，無需修正")
            return True
        c = changed
        area_emoji = "🏠" if c['area'] == "自己" else "🛋" if c['area'] == "公共" else "📦"
        time_disp = c['time']
        if len(time_disp) >= 16:
            time_disp = time_disp[5:16]
        reply(reply_token,
              f"✅ 已修正「{old_name}」→「{new_name}」\n"
              f"{area_emoji} {time_disp} ｜ {c['content']}")
        return True

    return False
