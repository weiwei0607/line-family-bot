"""
LINE 家庭群機器人 webhook
"""

import os
import re
import json
import requests
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, TextMessage,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

from sheets import (
    bg, get_members, get_chores, complete_chore, add_chore,
    get_weekly_points, format_weekly_summary, register_member,
    batch_log_points, get_shopping_list, add_shopping, complete_shopping,
    add_expense, get_expenses, get_member_weekly_breakdown,
    get_member_weekly_chore_points, WEEKLY_CAPS,
    add_declutter, get_declutter_list, complete_declutter,
    add_income, get_declutter_income, cancel_last_record,
)

app = Flask(__name__)

_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
_secret = os.environ.get("LINE_CHANNEL_SECRET", "")
configuration = Configuration(access_token=_token)
handler = WebhookHandler(_secret)
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
POINTS_THRESHOLD = int(os.environ.get("POINTS_THRESHOLD", "5"))

# ─── 工具函數 ─────────────────────────────────

def reply(reply_token: str, text: str):
    with ApiClient(configuration) as api_client:
        MessagingApi(api_client).reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=text[:4900])],
            )
        )

def call_gemini(prompt: str) -> str:
    if not GEMINI_KEY:
        return "（需要設定 GEMINI_API_KEY）"
    try:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/"
            f"models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
        )
        resp = requests.post(
            url,
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=20,
        )
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        return f"AI 回答失敗：{e}"

# ─── 指令處理 ─────────────────────────────────

def handle_chores(reply_token: str, member: str, text: str):
    """處理家事相關指令"""
    m = re.match(r"^(完成|做了|做好了|完成了)\s*(.+)", text)
    if m:
        chore_name = m.group(2).strip()
        result = complete_chore(chore_name, member or "不知道誰")
        if result and result.get("capped"):
            reply(reply_token,
                  f"⚠️ {member or '你'} 本週「{result['name']}」已達上限 {result['cap']} 點，不再計分喔！")
        elif result:
            pts = result["points"]
            pts_str = f"{pts:.2f}".rstrip('0').rstrip('.')
            summary = format_weekly_summary()
            reply(reply_token,
                  f"✅ {member or '你'} 完成了「{result['name']}」！獲得 {pts_str} 點 🎉\n\n{summary}")
        else:
            reply(reply_token,
                  f"找不到「{chore_name}」這個家事耶，確認一下名稱是否正確？\n"
                  f"輸入「家事清單」看看所有家事")
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

    m = re.match(r"^新增家事\s+(.+?)(\s+(\d+)點?)?$", text)
    if m:
        name = m.group(1).strip()
        pts = int(m.group(3)) if m.group(3) else 1
        bg(add_chore, name, pts)
        reply(reply_token, f"✅ 新增家事「{name}」（{pts}點），大家加油！")
        return True

    return False


def handle_points(reply_token: str, member: str, text: str):
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


def handle_shopping(reply_token: str, member: str, text: str):
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

    if text in ["購物清單", "要買什麼", "清單"]:
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


def handle_accounting(reply_token: str, member: str, text: str):
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
    if text == "斷捨離清單":
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


def handle_ai_mention(reply_token: str, text: str):
    """@機器人 問問題"""
    m = re.match(r"^@?(?:機器人|家管|bot|助理)\s+(.+)", text, re.IGNORECASE)
    if m:
        question = m.group(1).strip()
        answer = call_gemini(
            f"你是一個溫暖實用的家庭助理，用繁體中文回答，簡潔不囉嗦。\n\n問題：{question}"
        )
        reply(reply_token, answer)
        return True
    return False


def handle_admin(reply_token: str, event: MessageEvent, text: str):
    """管理指令"""
    if text in ["群組id", "群組ID", "groupid", "群id"]:
        source = event.source
        gid = getattr(source, "group_id", None) or getattr(source, "room_id", None) or "不是群組訊息"
        reply(reply_token, f"群組 ID：{gid}")
        return True

    m = re.match(r"^(?:我是|叫我|我叫)\s*(.+)", text)
    if m:
        name = m.group(1).strip()
        user_id = getattr(event.source, "user_id", "")
        approved = get_members()
        if name not in approved:
            names_str = "、".join(approved) if approved else "（尚未設定成員）"
            reply(reply_token, f"「{name}」不在成員名單裡喔！\n"
                               f"目前成員：{names_str}\n"
                               f"請用正確的家人稱呼 😊")
            return True
        if user_id and name:
            bg(register_member, user_id, name)
            _member_cache[user_id] = name
            reply(reply_token, f"好的！以後叫你「{name}」😊\n"
                               f"完成家事時傳「完成 家事名稱」就會記在你名下囉")
        return True

    return False


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


def handle_help(reply_token: str, text: str):
    if text in ["說明", "幫助", "功能", "help", "指令"]:
        reply(reply_token, """🏠 家管助理使用說明

【家事】
• 完成 [家事名稱] — 標記完成並獲點
• 家事清單 — 查所有家事及點數
• 新增家事 [名稱] [點數] — 新增項目

【點數】
• 查點數 — 全員本週排行
• 我的點數 — 看自己做了哪些

【購物】
• 買 [項目] — 加入購物清單
• 買好了 [項目] — 標記已購
• 購物清單 — 查看清單

【記帳】
• 記帳 [金額] [說明] — 記錄支出
• 今日帳 / 查帳 — 查今日/7天支出

【斷捨離】
• 斷捨離 [物品] — 加入待定區
• 丟了 [物品] — 標記丟棄
• 賣了 [物品] [金額] — 標記賣出並記入帳本
• 斷捨離清單 — 查看待定區
• 斷捨離收入 — 查賣出總收入

【AI 問答】
• @機器人 [問題] — 問任何問題

目標：每週家事點數達 5 點 🎯""")
        return True
    return False

# ─── Webhook 入口 ─────────────────────────────

@app.route("/")
def health():
    return "OK", 200

@app.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event: MessageEvent):
    if not hasattr(event, "reply_token") or not event.reply_token:
        return

    text = event.message.text.strip()
    reply_token = event.reply_token

    member = ""
    if hasattr(event, "source") and hasattr(event.source, "user_id"):
        member = _resolve_member(event.source.user_id)

    if (
        handle_admin(reply_token, event, text) or
        handle_batch_log(reply_token, member, text) or
        handle_help(reply_token, text) or
        handle_chores(reply_token, member, text) or
        handle_points(reply_token, member, text) or
        handle_shopping(reply_token, member, text) or
        handle_accounting(reply_token, member, text) or
        handle_declutter(reply_token, member, text) or
        handle_ai_mention(reply_token, text)
    ):
        return

    # 被 @ 提及時 AI 回答
    if hasattr(event, "message") and hasattr(event.message, "mention"):
        if event.message.mention:
            answer = call_gemini(
                f"你是一個溫暖實用的家庭助理，用繁體中文回答，簡潔不囉嗦。\n\n問題：{text}"
            )
            reply(reply_token, answer)


# user_id → 成員名對照
_member_cache: dict[str, str] = {}
_cache_ts: float = 0

def _resolve_member(user_id: str) -> str:
    import time
    global _cache_ts
    now = time.time()
    if now - _cache_ts > 600:
        _refresh_member_cache()
        _cache_ts = now
    return _member_cache.get(user_id, "")

def _refresh_member_cache():
    try:
        from sheets import _read
        rows = _read("設定", "A2:B30")
        for r in rows:
            if len(r) >= 2 and r[0].strip() and r[1].strip():
                _member_cache[r[1].strip()] = r[0].strip()
    except Exception:
        pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
