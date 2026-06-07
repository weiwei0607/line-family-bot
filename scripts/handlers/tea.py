"""Tea drinking daily check-in handler."""
from line_push import reply_text as reply
from sheets import add_tea_checkin, get_tea_checkins, get_members


def handle_tea(reply_token: str, member: str, text: str) -> bool:
    if text == "喝茶":
        if not member:
            reply(reply_token, "❓ 我不認識你，先傳「我是 XXX」讓我認識你")
            return True
        if add_tea_checkin(member):
            done = get_tea_checkins()
            all_members = get_members()
            pending = [m for m in all_members if m not in done]
            msg = f"🍵 {member} 今天喝茶打卡成功！"
            if pending:
                msg += f"\n還沒喝的：{'、'.join(pending)}"
            else:
                msg += "\n🎉 全家今天都喝了！"
        else:
            msg = f"✅ {member} 今天已經打卡過了，繼續保持！"
        reply(reply_token, msg)
        return True

    if text in ["喝茶狀態", "今日喝茶", "喝茶打卡"]:
        all_members = get_members()
        done = get_tea_checkins()
        pending = [m for m in all_members if m not in done]
        lines = ["🍵 今日喝茶狀態：\n"]
        for m in all_members:
            lines.append(f"{'✅' if m in done else '❌'} {m}")
        if not pending:
            lines.append("\n🎉 全家今天都喝了！")
        else:
            lines.append(f"\n還差 {len(pending)} 人，茶快過期了快喝！☕")
        reply(reply_token, "\n".join(lines))
        return True

    return False
