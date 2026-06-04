"""Domestic handlers: chores, points, shopping, accounting, fines, declutter."""

import os
import re
from line_push import reply_text as reply
from sheets import (
    complete_chore, get_chores, add_chore, format_weekly_summary,
    get_weekly_points, get_members, get_member_weekly_breakdown,
    cancel_last_record, log_chore_points, WEEKLY_CAPS, bg,
    add_shopping, complete_shopping, get_shopping_list,
    add_expense, get_expenses,
    pay_fine, get_outstanding_fines,
    add_declutter, get_declutter_list, complete_declutter, get_declutter_income, add_income,
)

POINTS_THRESHOLD = int(os.environ.get("POINTS_THRESHOLD", "5"))


def handle_chores(reply_token: str, member: str, text: str) -> bool:
    """處理家事相關指令（支援多行與結尾分數標記）"""
    m = re.match(r"^(完成|做了|做好了|完成了)\s*(.*)", text, re.DOTALL)
    if m:
        raw = m.group(2).strip()
        who = member or "不知道誰"
        successes, capped_list, not_found = [], [], []

        if raw:
            # 支援多行：按行拆分，移除純數字/空行，並去掉結尾分數標記（如「早餐 1」）
            lines = [line.strip() for line in raw.splitlines() if line.strip()]
            chore_names = []
            for line in lines:
                cleaned = re.sub(r'\s+\d+(?:\.\d+)?$', '', line).strip()
                if cleaned and not re.match(r'^\d+(?:\.\d+)?$', cleaned):
                    chore_names.append(cleaned)
        else:
            chore_names = []

        if not chore_names:
            reply(reply_token,
                  "請在「完成」後面加上家事名稱，例如：\n"
                  "完成 掃地\n"
                  "或一次列多項：\n"
                  "完成\n早餐\n午餐\n洗鍋")
            return True

        for chore_name in chore_names:
            result = complete_chore(chore_name, who)
            if result and result.get("capped"):
                capped_list.append(result["name"])
            elif result:
                pts_str = f"{result['points']:.2f}".rstrip('0').rstrip('.')
                log_chore_points(who, result["name"], result["points"])
                successes.append((result["name"], pts_str))
            else:
                not_found.append(chore_name)

        if not successes and not capped_list:
            reply(reply_token,
                  f"找不到「{raw}」這個家事耶，確認一下名稱是否正確？\n"
                  f"輸入「家事清單」看看所有家事")
        else:
            lines = []
            for name, pts_str in successes:
                lines.append(f"✅ {member or '你'} 完成了「{name}」！獲得 {pts_str} 點 🎉")
            for name in capped_list:
                lines.append(f"⚠️ 「{name}」本週已達上限，不再計分")
            for name in not_found:
                lines.append(f"❓ 找不到「{name}」")
            lines.append(f"\n{format_weekly_summary()}")
            reply(reply_token, "\n".join(lines))
        return True

    if text in ["家事清單", "家事", "待完成", "還有什麼家事"]:
        chores = get_chores()
        if not chores:
            reply(reply_token, "🎉 家事清單是空的！")
        else:
            lines = ["📋 家事清單：\n"]
            for c in chores:
                cap = WEEKLY_CAPS.get(c['name'])
                cap_str = f"（上限{cap}點/週）" if cap else ""
                lines.append(f"• {c['name']}  {c['points']}點{cap_str}")
            reply(reply_token, "\n".join(lines))
        return True

    m = re.match(r"^新增家事\s+(.+?)(\s+(\d+(?:\.\d+)?)點?)?$", text)
    if m:
        name = m.group(1).strip()
        pts = float(m.group(3)) if m.group(3) else 1
        bg(add_chore, name, pts)
        pts_str = f"{pts:.2f}".rstrip('0').rstrip('.')
        reply(reply_token, f"✅ 新增家事「{name}」（{pts_str}點），大家加油！")
        return True

    return False


def handle_points(reply_token: str, member: str, text: str) -> bool:
    """查詢點數"""
    if text in ["點數", "查點數", "點數排行", "積分", "本週點數"]:
        pts = get_weekly_points()
        members = get_members()
        lines = ["🏆 本週家事點數：\n"]
        for m in members:
            p = pts.get(m, 0)
            p_str = f"{p:.2f}".rstrip('0').rstrip('.')
            warn = " ⚠️ 未達標" if p < POINTS_THRESHOLD else " ✅"
            lines.append(f"{m}：{p_str} 點{warn}")
        lines.append(f"\n（目標：每週 {POINTS_THRESHOLD} 點以上）")
        reply(reply_token, "\n".join(lines))
        return True

    if text in ["我的點數", "我的紀錄", "我做了什麼", "我的家事"]:
        if not member:
            reply(reply_token, "還不知道你是誰，先傳「我是＿＿」讓我記住你 😊")
            return True
        breakdown = get_member_weekly_breakdown(member)
        total = sum(d["points"] for d in breakdown)
        total_str = f"{total:.2f}".rstrip('0').rstrip('.')
        if not breakdown:
            reply(reply_token, f"{member} 本週還沒有記錄，快去做家事！💪")
        else:
            lines = [f"📋 {member} 本週家事：\n"]
            for d in breakdown:
                p_str = f"{d['points']:.2f}".rstrip('0').rstrip('.')
                lines.append(f"• {d['name']}  {p_str}點")
            lines.append(f"\n合計：{total_str} 點")
            status = "✅ 已達標" if total >= POINTS_THRESHOLD else f"⚠️ 距目標還差 {POINTS_THRESHOLD - total:.2f}".rstrip('0').rstrip('.') + " 點"
            lines.append(status)
            reply(reply_token, "\n".join(lines))
        return True

    # 取消記錄
    m = re.match(r"^取消記錄\s*(.*)$", text)
    if m or text in ["取消上筆", "取消記錄"]:
        if not member:
            reply(reply_token, "還不知道你是誰，先傳「我是＿＿」讓我記住你 😊")
            return True
        chore_name = m.group(1).strip() if m and m.group(1).strip() else None
        result = cancel_last_record(member, chore_name)
        if result:
            p_str = f"{result['points']:.2f}".rstrip('0').rstrip('.')
            reply(reply_token, f"✅ 已取消「{result['name']}」的 {p_str} 點記錄")
        else:
            tip = f"「{chore_name}」的" if chore_name else ""
            reply(reply_token, f"找不到{tip}記錄，沒有東西可以取消")
        return True

    return False


def handle_shopping(reply_token: str, member: str, text: str) -> bool:
    """購物清單指令"""
    m = re.match(r"^(加購物|要買|買|購物加)\s+(.+)", text)
    if m:
        item = m.group(2).strip()
        bg(add_shopping, item, member or "")
        reply(reply_token, f"🛒 已加入購物清單：{item}")
        return True

    m = re.match(r"^(買好了|已買|買到了|買了)\s+(.+)", text)
    if m:
        item = m.group(2).strip()
        ok = complete_shopping(item, member or "")
        if ok:
            reply(reply_token, f"✅ 已標記「{item}」已購買 🛒")
        else:
            reply(reply_token, f"找不到「{item}」在購物清單裡喔")
        return True

    if text in ["購物清單", "要買什麼"]:
        items = get_shopping_list(only_pending=True)
        if not items:
            reply(reply_token, "🛒 購物清單是空的！")
        else:
            lines = ["🛒 待購物清單：\n"]
            for it in items:
                lines.append(f"• {it['name']}（{it['added_by']} 加的）")
            reply(reply_token, "\n".join(lines))
        return True

    return False


def handle_accounting(reply_token: str, member: str, text: str) -> bool:
    """家庭記帳"""
    m = re.match(r"^記帳\s+(\d+)\s+(.+?)(?:\s+(.+))?$", text)
    if m:
        amount = int(m.group(1))
        part2 = m.group(2).strip()
        part3 = m.group(3).strip() if m.group(3) else ""
        if part3:
            category, desc = part2, part3
        else:
            category, desc = "雜費", part2
        bg(add_expense, amount, category, desc, member or "")
        reply(reply_token,
              f"💰 已記帳：{category} - {desc}，{amount} 元\n（{member or ''}）")
        return True

    if text in ["帳", "帳目", "今日帳", "本週帳", "查帳"]:
        days = 1 if "今日" in text else 7
        exps = get_expenses(days=days)
        if not exps:
            reply(reply_token, f"最近 {days} 天沒有記帳紀錄")
        else:
            total = sum(e["amount"] for e in exps)
            label = "今日" if days == 1 else "最近7天"
            lines = [f"💰 {label}支出（共 {total} 元）：\n"]
            for e in exps[-10:]:
                lines.append(f"• {e['date']} {e['category']} {e['desc']} {e['amount']}元（{e['by']}）")
            reply(reply_token, "\n".join(lines))
        return True

    return False


def handle_fine(reply_token: str, member: str, text: str) -> bool:
    """罰款與欠款指令"""
    m = re.match(r"^繳罰款\s+(\d+)$", text)
    if m:
        if not member:
            reply(reply_token, "還不知道你是誰，先傳「我是＿＿」😊")
            return True
        amount = int(m.group(1))
        pay_fine(member, amount)
        balances = get_outstanding_fines(member=member)
        remaining = balances.get(member, 0)
        if remaining <= 0:
            reply(reply_token, f"✅ {member} 已繳 {amount} 元，欠款清零！小本本乾淨了 🎉")
        else:
            reply(reply_token, f"✅ {member} 已繳 {amount} 元，還欠 {remaining} 元")
        return True

    if text in ["欠款", "欠款清單", "小本本"]:
        balances = get_outstanding_fines()
        if not balances:
            reply(reply_token, "📒 小本本是空的，大家都沒有欠款 🎉")
        else:
            lines = ["📒 欠款小本本：\n"]
            for m_name, total in balances.items():
                if total > 0:
                    lines.append(f"  {m_name}：欠 {total} 元")
                elif total < 0:
                    lines.append(f"  {m_name}：多繳了 {-total} 元")
            lines.append("\n投幣後傳「繳罰款 金額」登記")
            reply(reply_token, "\n".join(lines))
        return True

    return False


def handle_declutter(reply_token: str, member: str, text: str) -> bool:
    """斷捨離指令"""
    # 加入待定區
    m = re.match(r"^斷捨離\s+(.+)", text)
    if m and text not in ["斷捨離清單", "斷捨離收入"]:
        item = m.group(1).strip()
        bg(add_declutter, item, member or "")
        reply(reply_token, f"🗂️ 「{item}」已加入待定區\n確定要處理時傳「丟了 {item}」或「賣了 {item} 金額」")
        return True

    # 查待定清單
    if text in ["斷捨離清單", "待定", "待定清單"]:
        items = get_declutter_list(only_pending=True)
        if not items:
            reply(reply_token, "🎉 待定區是空的，家裡很清爽！")
        else:
            lines = [f"🗂️ 斷捨離待定區（{len(items)} 項）：\n"]
            for it in items:
                lines.append(f"• {it['name']}（{it['added_by']} 加的）")
            lines.append("\n傳「丟了 物品名」或「賣了 物品名 金額」來處理")
            reply(reply_token, "\n".join(lines))
        return True

    # 丟棄
    m = re.match(r"^丟了\s+(.+)", text)
    if m:
        item = m.group(1).strip()
        result = complete_declutter(item, "丟棄", member or "")
        if result:
            reply(reply_token, f"🗑️ 「{item}」已丟棄！斷捨離成功 ✨")
        else:
            reply(reply_token, f"找不到「{item}」在待定區，先傳「斷捨離 {item}」加進去")
        return True

    # 賣出（帶金額）
    m = re.match(r"^賣了\s+(.+?)\s+(\d+)$", text)
    if m:
        item = m.group(1).strip()
        amount = int(m.group(2))
        result = complete_declutter(item, "賣出", member or "", amount)
        if result:
            bg(add_income, amount, f"賣掉：{item}", member or "")
            reply(reply_token, f"💰 「{item}」賣出 {amount} 元！\n已自動記入家庭帳本（斷捨離收入）✨")
        else:
            reply(reply_token, f"找不到「{item}」在待定區，先傳「斷捨離 {item}」加進去")
        return True

    # 賣出（沒帶金額）
    m = re.match(r"^賣了\s+(.+)", text)
    if m:
        item = m.group(1).strip()
        reply(reply_token, f"「{item}」賣了多少錢？請傳完整格式：\n「賣了 {item} 金額」")
        return True

    # 查斷捨離收入
    if text == "斷捨離收入":
        records = get_declutter_income()
        if not records:
            reply(reply_token, "目前還沒有斷捨離收入記錄")
        else:
            total = sum(r["amount"] for r in records)
            lines = [f"💰 斷捨離收入（共 {total} 元）：\n"]
            for r in records[-10:]:
                lines.append(f"• {r['date']} {r['desc']} {r['amount']}元（{r['by']}）")
            reply(reply_token, "\n".join(lines))
        return True

    return False
