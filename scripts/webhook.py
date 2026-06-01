"""
LINE 家庭群機器人 webhook
"""

import os
import logging
import time
import uuid

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
import re
import difflib
import requests
from flask import Flask, request, abort, g
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ReplyMessageRequest, TextMessage, ImageMessage,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, AudioMessageContent
from line_push import (
    reply_text as reply,
    push_messages,
)
from api_helpers import (
    format_weather_block, format_weather_day, format_weather_rain_check,
    parse_date_offset, get_trivia, get_open_trivia,
    smart_translate, text_to_speech, save_tts_audio, get_tts_audio,
    call_gemini, groq_stt, get_aqi,
)

from sheets import (
    bg, get_members, get_chores, complete_chore, add_chore,
    get_weekly_points, format_weekly_summary, register_member,
    batch_log_points, get_shopping_list, add_shopping, complete_shopping,
    add_expense, get_expenses, get_member_weekly_breakdown,
    get_member_weekly_chore_points, WEEKLY_CAPS,
    add_declutter, get_declutter_list, complete_declutter,
    add_income, get_declutter_income, cancel_last_record,
    pay_fine, get_outstanding_fines,
    rename_latest_tidy_member,
)

from handlers import (
    _handle_entertainment,
    _handle_finance,
    _handle_horoscope,
    _handle_images,
    _handle_language,
    _handle_tidy,
    _handle_tts,
    _handle_utils,
)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024  # 2MB max payload


@app.before_request
def _before_request():
    g.request_id = uuid.uuid4().hex[:12]
    g.start_time = time.time()


@app.after_request
def _after_request(response):
    duration_ms = (time.time() - g.start_time) * 1000
    logger.info(
        "[req:%s] %s %s -> %d in %.1fms",
        g.request_id, request.method, request.path,
        response.status_code, duration_ms,
    )
    return response

# 註冊 Daily Dose API
from dose_api import dose_bp
import logging
logger = logging.getLogger(__name__)
app.register_blueprint(dose_bp)

_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
_secret = os.environ.get("LINE_CHANNEL_SECRET", "")
configuration = Configuration(access_token=_token)
handler = WebhookHandler(_secret)
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
POINTS_THRESHOLD = int(os.environ.get("POINTS_THRESHOLD", "5"))

MEMBER_SIGNS = {
    "爸爸": "摩羯",
    "媽媽": "射手",
    "姊姊": "雙子",
    "妹妹": "金牛",
}

_quiz_state: dict[str, dict] = {}  # group_id -> {question, answer}
_HELP_TEXT_CACHE: str | None = None  # 指令清單快取

# ─── 工具函數 ─────────────────────────────────


# ── TTS 音檔公開路由 ───────────────────────────

@app.route("/tts/<filename>")
def serve_tts(filename: str):
    import re
    if not re.match(r'^tts_\d+\.m4a$', filename):
        abort(400)
    data = get_tts_audio(filename)
    if not data:
        abort(404)
    from flask import Response
    return Response(data[0], mimetype=data[1])


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

    m = re.match(r"^新增家事\s+(.+?)(\s+(\d+(?:\.\d+)?)點?)?$", text)
    if m:
        name = m.group(1).strip()
        pts = float(m.group(3)) if m.group(3) else 1
        bg(add_chore, name, pts)
        pts_str = f"{pts:.2f}".rstrip('0').rstrip('.')
        reply(reply_token, f"✅ 新增家事「{name}」（{pts_str}點），大家加油！")
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


def _handle_weather(reply_token: str, text: str) -> bool:
    """Handle weather-related commands."""
    weather_triggers = ["天氣", "下雨", "會下雨", "帶傘", "氣溫", "溫度", "適合出門", "出門嗎"]
    has_weather_word = any(k in text for k in weather_triggers)
    date_result = parse_date_offset(text)
    is_weather_cmd = text in ["天氣", "今天天氣", "天氣如何", "外面天氣"]

    if is_weather_cmd or has_weather_word or (date_result and ("嗎" in text or "?" in text or "？" in text)):
        if date_result:
            offset, desc = date_result
            if offset >= 7:
                reply(reply_token, f"❌ {desc} 超出7天預報範圍，目前只能查未來7天喔")
                return True
            if any(k in text for k in ["下雨", "會不會", "帶傘", "雨"]):
                reply(reply_token, format_weather_rain_check(offset, desc))
            else:
                a = get_aqi()
                weather_text = format_weather_day(offset)
                if offset == 0 and "error" not in a:
                    weather_text += f"\n\n空氣品質 AQI {a['aqi']}（{a['level']}）PM2.5：{a['pm25']}"
                reply(reply_token, f"🌡 {desc}天氣\n\n{weather_text}")
        else:
            reply(reply_token, "🌡 今日天氣\n\n" + format_weather_block())
        return True
    return False


def _handle_quiz(reply_token: str, text: str, group_id: str) -> bool:
    """Handle quiz game commands."""
    global _quiz_state
    if text in ["出題", "來玩問答", "問答遊戲", "出一題"]:
        trivia = get_open_trivia() or get_trivia()
        if trivia and trivia.get("question"):
            q_zh = smart_translate(trivia["question"])
            a_zh = smart_translate(trivia["answer"])
            _quiz_state[group_id] = {"question": q_zh, "answer": a_zh}
            reply(reply_token, f"🧠 問答時間！\n\n{q_zh}\n\n傳「答 你的答案」作答，傳「答案」看解答")
        else:
            qa = call_gemini("出一道適合全家的中文知識問答，格式：\n問題：xxx\n答案：xxx\n只給這兩行")
            question, answer = "", ""
            for line in qa.strip().splitlines():
                if line.startswith("問題："):
                    question = line[3:].strip()
                elif line.startswith("答案："):
                    answer = line[3:].strip()
            if question and answer:
                _quiz_state[group_id] = {"question": question, "answer": answer}
                reply(reply_token, f"🧠 問答時間！\n\n{question}\n\n傳「答 你的答案」作答，傳「答案」看解答")
            else:
                reply(reply_token, "出題失敗，再試一次！")
        return True

    m_ans = re.match(r"^答\s+(.+)$", text)
    if m_ans:
        if group_id not in _quiz_state:
            reply(reply_token, "目前沒有進行中的題目，傳「出題」開始！")
            return True
        state = _quiz_state[group_id]
        user_ans = m_ans.group(1).strip().lower()
        correct = state["answer"].lower()
        if correct in user_ans or user_ans in correct:
            del _quiz_state[group_id]
            reply(reply_token, f"🎉 答對了！答案是：{state['answer']}")
        else:
            reply(reply_token, "❌ 不對喔，再想想！")
        return True

    if text in ["答案", "我不知道", "放棄", "答案是什麼"]:
        if group_id in _quiz_state:
            state = _quiz_state.pop(group_id)
            reply(reply_token, f"💡 答案是：{state['answer']}")
            return True
    return False


def handle_fun(reply_token: str, source, text: str, member: str = "") -> bool:

    group_id = getattr(source, "group_id", None) or getattr(source, "room_id", "default")

    # ── Simple dispatch (fast path for stateless commands) ──
    from dispatch_fun import try_dispatch
    if try_dispatch(text, lambda t: reply(reply_token, t)):
        return True

    # ── 天氣 ──
    if _handle_weather(reply_token, text):
        return True

    # ── 收拾紀錄 ──
    if _handle_tidy(reply_token, text, member, source, configuration):
        return True

    # ── 星座運勢 ──
    if _handle_horoscope(reply_token, text, MEMBER_SIGNS):
        return True

    # ── 問答遊戲 ──
    if _handle_quiz(reply_token, text, group_id):
        return True

    # ── 娛樂 ──
    if _handle_entertainment(reply_token, text):
        return True

    # ── 圖片 ──
    if _handle_images(reply_token, text):
        return True

    # ── 工具 ──
    if _handle_utils(reply_token, text):
        return True

    # ── 金融 ──
    if _handle_finance(reply_token, text):
        return True

    # ── 語言 ──
    if _handle_language(reply_token, text):
        return True

    # ── 念出來（TTS）──
    if _handle_tts(reply_token, text):
        return True

    return False


def handle_ai_mention(reply_token: str, text: str):
    """@機器人 問問題"""
    m = re.match(r"^@?(?:機器人|家管|bot|助理|小花)\s+(.+)", text, re.IGNORECASE)
    if m:
        question = m.group(1).strip()
        answer = call_gemini(
            f"你是一個溫暖實用的家庭助理，用繁體中文回答，簡潔不囉嗦。\n\n問題：{question}"
        )
        reply(reply_token, answer)
        return True
    return False


def handle_admin(reply_token: str, source, text: str):
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
            _member_cache[user_id] = name
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
        # time 欄位已含完整日期時間，取 MM/DD HH:MM 顯示
        time_disp = c['time']
        if len(time_disp) >= 16:
            time_disp = time_disp[5:16]  # YYYY-MM-DD HH:MM → MM-DD HH:MM
        reply(reply_token,
              f"✅ 已修正「{old_name}」→「{new_name}」\n"
              f"{area_emoji} {time_disp} ｜ {c['content']}")
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
    global _HELP_TEXT_CACHE
    if text in ["說明", "幫助", "功能", "help", "指令", "指令清單", "清單"]:
        if _HELP_TEXT_CACHE is None:
            _HELP_TEXT_CACHE = """🏠 家管助理指令清單

【家事】
• 完成 [家事名稱]
• 完成（換行列多項家事）— 批量記錄
• 家事清單 — 查所有家事
• 新增家事 [名稱] [點數]

【點數】
• 查點數 — 全員本週排行
• 我的點數 — 自己本週明細
• 取消記錄 [家事名稱] — 取消最近一筆

【購物】
• 買 [項目] — 加入購物清單
• 買好了 [項目] — 標記已購
• 購物清單 — 查看清單

【記帳】
• 記帳 [金額] [說明] — 記錄支出
• 今日帳 / 查帳 — 查今日/7天支出

【罰款】
• 繳罰款 [金額] — 投幣後登記
• 欠款 / 小本本 — 查累積欠款

【斷捨離】
• 斷捨離 [物品] — 加入待定區
• 丟了 [物品] — 標記丟棄
• 賣了 [物品] [金額] — 賣出並記帳
• 斷捨離清單 — 查待定區
• 斷捨離收入 — 查賣出總收入

【生活小工具】
• 天氣 — 今日天氣 + 空氣品質
• [日期]天氣 / [日期]會下雨嗎 — 支援「今天/明天/後天/星期三/下週五」等
• 收拾 — 全家收拾紀錄 + 欠次統計
• 收拾 [內容] — 報備自己/公共區域收拾
• 今天吃什麼 — 隨機世界料理食譜
• [星座]運勢 — 例：天蠍座運勢
• 今日全員運勢 — 全家人運勢一次看
• 出題 — 家庭問答遊戲（答 xxx 作答）
• 笑話 / 說個笑話 / Chuck Norris
• 推薦飲料 [名稱] — 飲料食譜
• 今天做什麼 — 隨機休閒活動
• 今天運動 — 隨機運動建議
• 動漫名言 / 電影台詞 / 激勵名言
• 小花畫 [描述] — AI 生成圖片
• 匯率 [幣別] — 例：匯率 美金
• 金價 — 今日黃金價格
• 推薦電影 / 電影 [片名]
• 哪裡看 [片名] — 查串流平台
• BMI [身高] [體重] — 例：BMI 165 55
• 食譜 [食材] — 依食材找食譜
• 熱量 [食物] / 消耗熱量 [活動] [分鐘]
• 冷知識 / 天文冷知識 / 數字冷知識
• 今日宇宙 / NASA — 每日天文圖片
• 給我建議

【語言學習】
• 日文 [單字] — 查讀音 + 意思 + JLPT
• 今日日文單字 — 隨機 N5 單字
• 漢字 [字] — 查漢字讀音筆畫
• 今日漢字 — 隨機漢字 + 例句
• 西文 [單字] — 查西班牙文
• 今日西文單字 — 隨機西班牙文

【其他】
• 我是 [名字] — 登記身分
• 助理 [問題] / 小花 [問題] — AI 問答

目標：每週 5 點，少一點罰 50 元 🎯"""
        reply(reply_token, _HELP_TEXT_CACHE)
        return True
    return False

# ─── Webhook 入口 ─────────────────────────────

@app.route("/")
@app.route("/health")
def health():
    checks = {}
    # 1. SQLite TTS store
    try:
        from tts_store import get_tts_audio
        get_tts_audio("__health__")
        checks["tts_db"] = "ok"
    except Exception as e:
        checks["tts_db"] = f"fail: {e}"

    # 2. LINE API connectivity
    try:
        import requests
        token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
        if token:
            r = requests.get(
                "https://api.line.me/v2/bot/info",
                headers={"Authorization": f"Bearer {token}"},
                timeout=5,
            )
            checks["line_api"] = "ok" if r.status_code == 200 else f"warn: {r.status_code}"
        else:
            checks["line_api"] = "skip: no token"
    except Exception as e:
        checks["line_api"] = f"fail: {e}"

    # 3. Google Sheets token check
    try:
        from sheets import _get_service
        _get_service()
        checks["sheets"] = "ok"
    except Exception as e:
        checks["sheets"] = f"fail: {e}"

    all_ok = all(v == "ok" for v in checks.values())
    status = 200 if all_ok else 503
    return checks, status


@app.route("/daily_push", methods=["POST"])
def daily_push():
    """早安推播（含 TTS），由 GitHub Actions 每天呼叫"""
    cron_secret = os.environ.get("CRON_SECRET", "")
    token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    if not cron_secret or not token or token != cron_secret:
        abort(403)

    # Idempotency: skip if already ran today
    from tts_store import cron_is_done, cron_mark_done
    if cron_is_done("daily_push"):
        return "Already done today", 200

    from sheets import get_members, get_chores, get_weekly_points
    from api_helpers import format_weather_block

    group_id = os.environ.get("LINE_GROUP_ID", "")
    if not group_id:
        return "LINE_GROUP_ID not set", 500

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=3) as ex:
        f_members = ex.submit(get_members)
        f_pts     = ex.submit(get_weekly_points)
        f_chores  = ex.submit(get_chores)
        members = f_members.result()
        pts     = f_pts.result()
        chores  = f_chores.result()
    low_pts = [m for m in members if pts.get(m, 0) < POINTS_THRESHOLD]

    lines = ["☀️ 早安！家管助理日報\n"]
    lines.append(format_weather_block())
    lines.append("")
    if chores:
        lines.append(f"📋 今日待完成家事（共 {len(chores)} 項）：")
        for c in chores[:8]:
            lines.append(f"  • {c['name']}（{c['points']}點）")
    else:
        lines.append("🎉 今日家事全部完成！大家辛苦了！")
    lines.append("")
    if low_pts:
        lines.append("⚠️ 本週點數還不夠的成員：")
        for m in low_pts:
            lines.append(f"  {m}：目前 {pts.get(m,0)} 點（目標 {POINTS_THRESHOLD} 點）")
        lines.append("\n快去完成家事累積點數吧！💪")
    else:
        lines.append("✅ 大家本週點數都達標了，棒棒！🎉")
    lines.append("\n輸入「家事清單」查看待完成家事")
    text_body = "\n".join(lines)

    # 先送文字
    push_messages(group_id, [{"type": "text", "text": text_body[:4900]}])

    # 再送 TTS 語音（早安問候）
    base_url = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
    if base_url:
        greeting = f"早安！今天天氣{'不錯，出門記得防曬！' if '晴' in text_body else '要注意，出門帶傘喔！'}"
        tts_result = text_to_speech(greeting, "zh-TW")
        if tts_result:
            audio_bytes, mime = tts_result
            fname = save_tts_audio(audio_bytes, mime)
            audio_url = f"{base_url}/tts/{fname}"
            duration = min(len(greeting) * 300 + 1000, 30000)
            push_messages(group_id, [{"type": "audio", "originalContentUrl": audio_url, "duration": duration}])

    cron_mark_done("daily_push")
    return "OK"


@app.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)

    # Deduplication: skip duplicate webhook deliveries
    import hashlib
    from tts_store import webhook_seen
    dedup_key = hashlib.sha256(body.encode()).hexdigest()[:32]
    if webhook_seen(dedup_key, ttl_seconds=60):
        return "OK", 200

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

def _process_text_message(reply_token: str, text: str, source, member: str = ""):
    """處理文字訊息的核心邏輯（文字/語音轉文字共用）"""
    if (
        handle_admin(reply_token, source, text) or
        handle_batch_log(reply_token, member, text) or
        handle_help(reply_token, text) or
        handle_chores(reply_token, member, text) or
        handle_points(reply_token, member, text) or
        handle_shopping(reply_token, member, text) or
        handle_accounting(reply_token, member, text) or
        handle_fine(reply_token, member, text) or
        handle_declutter(reply_token, member, text) or
        handle_fun(reply_token, source, text, member) or
        handle_ai_mention(reply_token, text)
    ):
        return

    # 被 @ 提及時 AI 回答
    if hasattr(source, "mention") and source.mention:
        answer = call_gemini(
            f"你是一個溫暖實用的家庭助理，用繁體中文回答，簡潔不囉嗦。\n\n問題：{text}"
        )
        reply(reply_token, answer)
        return

    # 拼字容錯：短指令找最接近的
    _KNOWN_COMMANDS = [
        "家事清單", "點數", "我的點數", "購物清單", "帳目", "欠款",
        "天氣", "今天吃什麼", "星座", "今日全員運勢", "笑話", "冷知識",
        "今日宇宙", "推薦電影", "新聞", "今日新聞", "金價", "激勵名言",
        "今日日文單字", "今日西文單字", "今日漢字", "說明", "指令清單",
        "今天做什麼", "今天運動", "動漫名言", "出題", "翻譯",
    ]
    if len(text) <= 8 and not re.search(r"[a-zA-Z0-9]", text):
        close = difflib.get_close_matches(text, _KNOWN_COMMANDS, n=1, cutoff=0.6)
        if close:
            reply(reply_token, f"你是想說「{close[0]}」嗎？試試傳那個指令 😊")


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event: MessageEvent):
    if not hasattr(event, "reply_token") or not event.reply_token:
        return

    text = event.message.text.strip()
    reply_token = event.reply_token

    user_id = ""
    if hasattr(event, "source") and hasattr(event.source, "user_id"):
        user_id = event.source.user_id

    # Rate limiting (30 requests / 60s per user)
    if user_id and not rate_limit_check(user_id, max_requests=30, window_seconds=60):
        reply(reply_token, "⏳ 你發太快了，請稍後再試 👋")
        return

    member = _resolve_member(user_id) if user_id else ""
    _process_text_message(reply_token, text, event.source, member)


# ── 語音訊息處理（Speech-to-Text）────────────────

@handler.add(MessageEvent, message=AudioMessageContent)
def handle_audio_message(event: MessageEvent):
    """接收語音訊息，下載音檔後用 Gemini 轉文字，再當作文本處理"""
    if not hasattr(event, "reply_token") or not event.reply_token:
        return

    reply_token = event.reply_token
    user_id = getattr(event.source, "user_id", "")

    # Rate limiting for audio (10 / 60s)
    if user_id and not rate_limit_check(user_id, max_requests=10, window_seconds=60):
        reply(reply_token, "⏳ 語音發太快了，請稍後再試 👋")
        return

    audio = event.message

    # 取得音檔 URL
    audio_url = None
    if hasattr(audio, "content_provider") and audio.content_provider:
        cp = audio.content_provider
        if hasattr(cp, "original_content_url") and cp.original_content_url:
            audio_url = cp.original_content_url
        elif hasattr(cp, "content_url") and cp.content_url:
            audio_url = cp.content_url

    if not audio_url:
        reply(reply_token, "🎤 無法取得語音檔案，請確認設定")
        return

    # SSRF guard: only allow LINE content-provider domains
    from urllib.parse import urlparse
    parsed = urlparse(audio_url)
    allowed_hosts = ("api-data.line.me", "data.line.me")
    if parsed.scheme != "https" or parsed.hostname not in allowed_hosts:
        reply(reply_token, "🎤 語音來源不合法")
        return

    # 下載音檔
    try:
        r = requests.get(audio_url, timeout=15)
        r.raise_for_status()
        audio_bytes = r.content
    except Exception as e:
        reply(reply_token, f"🎤 語音下載失敗：{e}")
        return

    # ── 語音轉文字：Groq Whisper 優先，Gemini 作 fallback ──
    transcript = groq_stt(audio_bytes, "audio/mpeg")

    if not transcript and GEMINI_KEY:
        try:
            import base64
            audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
            url = (
                "https://generativelanguage.googleapis.com/v1beta/"
                f"models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
            )
            payload = {
                "contents": [{
                    "parts": [
                        {"text": "請把這段語音轉成文字，只給轉錄結果，不要任何解釋。如果是中文請用繁體中文。"},
                        {"inline_data": {"mime_type": "audio/mpeg", "data": audio_b64}},
                    ]
                }]
            }
            resp = requests.post(url, json=payload, timeout=30)
            transcript = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        except Exception as e:
            reply(reply_token, f"🎤 語音轉文字失敗：{e}")
            return

    if not transcript:
        reply(reply_token, "🎤 語音轉文字無法使用，請設定 GROQ_API_KEY 或 GEMINI_API_KEY")
        return

    if not transcript:
        reply(reply_token, "🎤 聽不清楚，請再說一次")
        return

    # 告訴使用者聽到了什麼
    reply(reply_token, f"🎤 聽到：「{transcript[:80]}{'...' if len(transcript) > 80 else ''}」")

    # 繼續當作文本處理
    member = ""
    if hasattr(event, "source") and hasattr(event.source, "user_id"):
        member = _resolve_member(event.source.user_id)

    _process_text_message(reply_token, transcript, event.source, member)


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
    except Exception as _exc:
        logger.warning("Silent error: %s", _exc)


from utils import send_telegram_alert, rate_limit_check

@app.errorhandler(Exception)
def _handle_error(e):
    import traceback
    err_msg = f"家管助理異常：{type(e).__name__}\n{str(e)[:200]}"
    logging.error("Unhandled exception: %s", err_msg)
    traceback.print_exc()
    send_telegram_alert(err_msg)
    return "Internal Server Error", 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, threaded=True)
