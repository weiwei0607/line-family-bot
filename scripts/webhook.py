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
    get_weekly_points, get_shopping_list, add_shopping, complete_shopping,
    add_expense, get_expenses,
)

app = Flask(__name__)

_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
_secret = os.environ.get("LINE_CHANNEL_SECRET", "")
configuration = Configuration(access_token=_token)
handler = WebhookHandler(_secret)
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
POINTS_THRESHOLD = int(os.environ.get("POINTS_THRESHOLD", "5"))  # 每週最低點數

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

def extract_member(text: str) -> str:
    """從訊息嘗試提取成員名字，回傳空字串代表未知"""
    members = get_members()
    for m in members:
        if m in text:
            return m
    return ""

# ─── 指令處理 ─────────────────────────────────

def handle_chores(reply_token: str, member: str, text: str):
    """處理家事相關指令"""
    # 完成家事：「完成 洗碗」「做了 掃地」
    m = re.match(r"^(完成|做了|做好了|完成了)\s*(.+)", text)
    if m:
        chore_name = m.group(2).strip()
        result = complete_chore(chore_name, member or "不知道誰")
        if result:
            pts = result["points"]
            reply(reply_token,
                  f"✅ {member or '你'} 完成了「{result['name']}」！\n"
                  f"獲得 {pts} 點，辛苦了 🎉")
        else:
            reply(reply_token,
                  f"找不到「{chore_name}」這個家事耶，確認一下名稱是否正確？\n"
                  f"輸入「家事清單」看看所有待完成家事")
        return True

    # 查家事清單
    if text in ["家事清單", "家事", "待完成", "還有什麼家事"]:
        chores = get_chores(only_pending=True)
        if not chores:
            reply(reply_token, "🎉 所有家事都完成了！家裡超乾淨的～")
        else:
            lines = ["📋 待完成家事：\n"]
            for c in chores:
                lines.append(f"• {c['name']}（{c['points']}點）")
            reply(reply_token, "\n".join(lines))
        return True

    # 新增家事（管理員用）：「新增家事 洗碗 2點」
    m = re.match(r"^新增家事\s+(.+?)(\s+(\d+)點?)?$", text)
    if m:
        name = m.group(1).strip()
        pts = int(m.group(3)) if m.group(3) else 1
        bg(add_chore, name, pts)
        reply(reply_token, f"✅ 新增家事「{name}」（{pts}點），大家加油！")
        return True

    return False


def handle_points(reply_token: str, text: str):
    """查詢點數排行"""
    if text in ["點數", "查點數", "點數排行", "積分", "本週點數"]:
        pts = get_weekly_points()
        members = get_members()
        lines = ["🏆 本週家事點數：\n"]
        for m in members:
            p = pts.get(m, 0)
            warn = " ⚠️ 未達標" if p < POINTS_THRESHOLD else " ✅"
            lines.append(f"{m}：{p} 點{warn}")
        lines.append(f"\n（目標：每週 {POINTS_THRESHOLD} 點以上）")
        reply(reply_token, "\n".join(lines))
        return True
    return False


def handle_shopping(reply_token: str, member: str, text: str):
    """購物清單指令"""
    # 新增購物：「加購物 牛奶」「買 洗髮精」
    m = re.match(r"^(加購物|要買|買|購物加)\s+(.+)", text)
    if m:
        item = m.group(2).strip()
        bg(add_shopping, item, member or "")
        reply(reply_token, f"🛒 已加入購物清單：{item}")
        return True

    # 購物完成：「買好了 牛奶」「已買 洗髮精」
    m = re.match(r"^(買好了|已買|買到了|買了)\s+(.+)", text)
    if m:
        item = m.group(2).strip()
        ok = complete_shopping(item, member or "")
        if ok:
            reply(reply_token, f"✅ 已標記「{item}」已購買 🛒")
        else:
            reply(reply_token, f"找不到「{item}」在購物清單裡喔")
        return True

    # 查購物清單
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
    # 記帳格式：「記帳 250 飲食 買晚餐」或「記帳 250 買晚餐」
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

    # 查帳
    if text in ["帳", "帳目", "今日帳", "本週帳", "查帳"]:
        days = 1 if "今日" in text else 7
        exps = get_expenses(days=days)
        if not exps:
            reply(reply_token, f"最近 {days} 天沒有記帳紀錄")
        else:
            total = sum(e["amount"] for e in exps)
            lines = [f"💰 最近 {days} 天支出（共 {total} 元）：\n"]
            for e in exps[-10:]:
                lines.append(f"• {e['date']} {e['category']} {e['desc']} {e['amount']}元（{e['by']}）")
            reply(reply_token, "\n".join(lines))
        return True

    return False


def handle_ai_mention(reply_token: str, text: str):
    """@機器人 問問題"""
    # 支援：@家管 問題、機器人 問題、@bot 問題
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
    """管理指令（取群組 ID 等）"""
    if text in ["群組id", "群組ID", "groupid", "群id"]:
        source = event.source
        gid = getattr(source, "group_id", None) or getattr(source, "room_id", None) or "不是群組訊息"
        reply(reply_token, f"群組 ID：{gid}")
        return True
    return False


def handle_help(reply_token: str, text: str):
    if text in ["說明", "幫助", "功能", "help", "指令"]:
        reply(reply_token, """🏠 家管助理使用說明

【家事】
• 完成 [家事名稱] — 標記完成並獲點
• 家事清單 — 查待完成家事
• 新增家事 [名稱] [點數] — 新增項目

【點數】
• 查點數 — 看本週大家的點數排行

【購物】
• 買 [項目] — 加入購物清單
• 買好了 [項目] — 標記已購
• 購物清單 — 查看清單

【記帳】
• 記帳 [金額] [說明] — 記錄支出
• 查帳 — 查最近7天

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

    # 辨識發言成員（需在群組中可辨識）
    member = ""
    if hasattr(event, "source") and hasattr(event.source, "user_id"):
        # 嘗試從暱稱匹配 — 簡化做法：直接從文字或設定取名
        # 可在 設定 tab 第二欄設 user_id 對應名字
        member = _resolve_member(event.source.user_id)

    if (
        handle_admin(reply_token, event, text) or
        handle_help(reply_token, text) or
        handle_chores(reply_token, member, text) or
        handle_points(reply_token, text) or
        handle_shopping(reply_token, member, text) or
        handle_accounting(reply_token, member, text) or
        handle_ai_mention(reply_token, text)
    ):
        return

    # 如果在群組中被@提及，嘗試 AI 回答
    if hasattr(event, "message") and hasattr(event.message, "mention"):
        if event.message.mention:
            answer = call_gemini(
                f"你是一個溫暖實用的家庭助理，用繁體中文回答，簡潔不囉嗦。\n\n問題：{text}"
            )
            reply(reply_token, answer)


# user_id → 成員名對照（從設定 tab 讀）
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
                _member_cache[r[1].strip()] = r[0].strip()  # user_id → 名字
    except Exception:
        pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
