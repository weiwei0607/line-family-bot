"""
LINE 家庭群機器人 webhook
"""

import os
import logging
import time
import uuid
import threading
import hmac
import hashlib
import base64
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
import re
import difflib
import requests
from flask import Flask, request, abort, g
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import Configuration
from linebot.v3.webhooks import MessageEvent, TextMessageContent, AudioMessageContent, ImageMessageContent
from line_push import (
    reply_text as reply,
    push_messages,
)
from api_helpers import (
    text_to_speech, save_tts_audio, get_tts_audio,
    call_gemini, call_ai, groq_stt,
)

from handlers.admin import handle_admin
from handlers.batch_log import handle_batch_log
from handlers.domestic import (
    handle_accounting,
    handle_chores,
    handle_declutter,
    handle_fine,
    handle_points,
    handle_shopping,
)
from handlers.help import handle_help
from handlers.member_cache import resolve_member
from handlers.tea import handle_tea
from handlers.tidy import _handle_tidy
from handlers.todos import (
    handle_add_todo,
    handle_cancel_todo,
    handle_complete_todo,
    handle_view_todos,
)
from vacuum_tracker import handle as vacuum_handle

# 只有當用戶明確要求「看書回答」時才注入知識庫
_KB_TRIGGER_WORDS = ["看書", "根據書", "參考書", "用書", "知識庫", "讀過的書", "家裡的書", "書上說", "書裡說", "根據我們家"]

def _should_inject_kb(text: str) -> bool:
    return any(w in text for w in _KB_TRIGGER_WORDS)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024  # 2MB max payload

import memory as _memory
from sheets import bg as _bg
_bg(_memory.load_from_sheets)  # 啟動時從 Sheets 還原對話歷史

# ── 家庭狀態簽名（附在每則回覆末尾）────────────────────────────────────────
_footer_cache: dict = {"v": None, "ts": 0.0}
_FOOTER_TTL = 180  # 3 分鐘

def _get_family_footer() -> str:
    now = time.time()
    if _footer_cache["v"] is not None and now - _footer_cache["ts"] < _FOOTER_TTL:
        return _footer_cache["v"]
    try:
        from sheets import get_members, get_weekly_points, get_tea_checkins
        from datetime import datetime as _dt2
        from zoneinfo import ZoneInfo as _ZI
        today = _dt2.now(_ZI("Asia/Taipei")).strftime("%Y-%m-%d")

        from sheets import get_tidy_debt
        members = get_members()
        pts = get_weekly_points()
        tea_done = get_tea_checkins(today)
        debt = get_tidy_debt()

        lines = []
        low_pts = [(m, round(pts.get(m, 0), 1)) for m in members if pts.get(m, 0) < POINTS_THRESHOLD]
        if low_pts:
            detail = "、".join(f"{m}（{p}點）" for m, p in low_pts)
            lines.append(f"⚠️ 點數不夠：{detail}")

        no_tea = [m for m in members if m not in tea_done]
        if no_tea:
            lines.append(f"🍵 未喝茶：{'、'.join(no_tea)}")

        owe_public = [m for m in members if debt.get(m, {}).get("公共", 0) > 0]
        owe_self = [m for m in members if debt.get(m, {}).get("自己", 0) > 0]
        if owe_public:
            detail = "、".join(f"{m}（{debt[m]['公共']}天）" for m in owe_public)
            lines.append(f"🏠 欠公共收拾：{detail}")
        if owe_self:
            detail = "、".join(f"{m}（{debt[m]['自己']}天）" for m in owe_self)
            lines.append(f"🛋️ 欠自己收拾：{detail}")

        footer = ("\n─────────────\n" + "\n".join(lines)) if lines else ""
        _footer_cache["v"] = footer
        _footer_cache["ts"] = now
        return footer
    except Exception:
        return ""


def _invalidate_footer():
    _footer_cache["ts"] = 0.0


# 包裝 reply，讓機器人回覆自動記入短暫記憶（跳過錯誤訊息），並附家庭狀態簽名
_ERROR_PREFIXES = ("❌", "⚠️", "⏳", "🚫")
_raw_reply = reply
def reply(token: str, text: str, **kw):
    if text and not text.startswith(_ERROR_PREFIXES):
        _memory.record_ephemeral("機器人", text)
        footer = _get_family_footer()
        if footer:
            text = text + footer
    return _raw_reply(token, text, **kw)


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

# 註冊 Daily Dose API（可選，沒用到就關掉省記憶體）
import logging
logger = logging.getLogger(__name__)
if os.environ.get("ENABLE_DOSE_API", "").lower() in ("1", "true", "yes"):
    from dose_api import dose_bp
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

# ─── 工具函數 ─────────────────────────────────


# ── TTS 音檔公開路由 ───────────────────────────

@app.route("/tts/<filename>")
def serve_tts(filename: str):
    import re
    if not re.match(r'^tts_\d+\.(m4a|mp3)$', filename):
        abort(400)
    data = get_tts_audio(filename)
    if not data:
        abort(404)
    from flask import Response
    return Response(data[0], mimetype=data[1])


@app.route("/apod/<filename>")
def serve_apod(filename: str):
    import re
    from flask import send_file
    if not re.match(r'^apod_\d+\.jpg$', filename):
        abort(400)
    path = f"/tmp/apod_files/{filename}"
    if not os.path.exists(path):
        abort(404)
    return send_file(path, mimetype="image/jpeg")


# ─── 指令處理 ─────────────────────────────────



def handle_fun(reply_token: str, source, text: str, member: str = "") -> bool:

    group_id = getattr(source, "group_id", None) or getattr(source, "room_id", "default")

    # ── 收拾紀錄（優先於小白，避免「收拾清單」被集塵盒關鍵字攔截）──
    if _handle_tidy(reply_token, text, member, source, configuration):
        return True

    # ── 小白（掃地機器人）維護紀錄 ──
    reply_text = vacuum_handle(text, user=member or "家人")
    if reply_text:
        reply(reply_token, reply_text)
        return True

    # ── Simple dispatch (fast path for stateless commands) ──
    from dispatch_fun import try_dispatch
    if try_dispatch(text, lambda t: reply(reply_token, t)):
        return True

    # ── 趣味互動（骰子、猜拳、配對）──
    if text.startswith("配對"):
        from handlers.games import handle_pairing
        reply(reply_token, handle_pairing(text))
        return True
    if re.search(r'搖骰子|擲骰子|搖\d*[顆個]骰', text):
        from handlers.games import handle_dice
        reply(reply_token, handle_dice(text))
        return True
    if text.startswith("猜拳"):
        from handlers.games import handle_rps
        reply(reply_token, handle_rps(text))
        return True

    # ── 投票 ──
    from handlers.vote import handle_vote
    vote_result = handle_vote(text, group_id, member)
    if vote_result is not None:
        reply(reply_token, vote_result)
        return True

    # ── 天氣 ──
    from handlers.weather import _handle_weather
    if _handle_weather(reply_token, text):
        return True

    # ── 星座運勢 ──
    from handlers.horoscope import _handle_horoscope
    if _handle_horoscope(reply_token, text, MEMBER_SIGNS):
        return True

    # ── 問答遊戲 ──
    from handlers.quiz import _handle_quiz
    if _handle_quiz(reply_token, text, group_id):
        return True

    # ── 娛樂 ──
    from handlers.entertainment import _handle_entertainment
    if _handle_entertainment(reply_token, text):
        return True

    # ── 圖片 ──
    from handlers.images import _handle_images
    if _handle_images(reply_token, text):
        return True

    # ── 工具 ──
    from handlers.utils import _handle_utils
    if _handle_utils(reply_token, text):
        return True

    # ── 金融 ──
    from handlers.finance import _handle_finance
    if _handle_finance(reply_token, text):
        return True

    # ── 語言 ──
    from handlers.language import _handle_language
    if _handle_language(reply_token, text):
        return True

    # ── 念出來（TTS）──
    from handlers.tts import _handle_tts
    if _handle_tts(reply_token, text):
        return True

    return False


_IS_XIAOHUA = re.compile(r"^@?小花\s*(.+)", re.IGNORECASE)
_IS_XIAOHUA_ALONE = re.compile(r"^@?小花[！!～~？?。]*$", re.IGNORECASE)
_IS_BOT     = re.compile(r"^@?(?:機器人|家管|bot|助理)\s*(.+)", re.IGNORECASE)

def handle_ai_mention(reply_token: str, text: str, member: str = ""):
    """@小花 / @機器人 問問題（純文字觸發，非 LINE 正式 mention）"""
    # 單獨叫名字：打招呼
    if _IS_XIAOHUA_ALONE.match(text):
        import random
        greetings = [
            "幹嘛～ 叫我做什麼 😏",
            "有事嗎？說吧！🌸",
            "在的在的～ 什麼事？",
            "叫我？🌷",
            "欸！我在！說～",
        ]
        reply(reply_token, random.choice(greetings))
        return True

    m_xh = _IS_XIAOHUA.match(text)
    m_bot = _IS_BOT.match(text)
    m = m_xh or m_bot
    if not m:
        return False

    question = m.group(1).strip()
    if not question:
        reply(reply_token, "嗯？你想問什麼呢？😊")
        return True

    try:
        _memory.record(member or "家人", question)
        if handle_fun(reply_token, None, question):
            return True

        ctx = _memory.format_for_ai()
        img_desc = ""
        if m_xh and any(k in question for k in ["圖", "看", "照片", "拍"]):
            group_id = getattr(_memory._ctx, "group_id", "default")
            img_desc = _analyze_group_images(group_id)

        if m_xh:
            persona = (
                "你叫小花，是這個家的 AI 助手，個性溫柔但偶爾小毒舌，會用可愛的語氣說話。"
                "你喜歡加 emoji 但不過分。你記得這個家發生過的事。"
                "用繁體中文回答，簡短有趣。"
            )
        else:
            persona = "你是一個溫暖實用的家庭助理，用繁體中文回答，簡潔不囉嗦。"

        # 只有用戶要求「看書回答」時才注入知識庫
        if _should_inject_kb(question):
            from handlers.books import find_relevant_context as _kb_context
            kb = _kb_context(question)
        else:
            kb = ""
        prompt = (
            persona
            + (f"\n\n{ctx}" if ctx else "")
            + (f"\n\n{img_desc}" if img_desc else "")
            + (f"\n\n---\n\n{kb}\n\n---" if kb else "")
            + f"\n\n{member or '家人'}：{question}"
        )
        answer = call_ai(prompt)
        if not answer:
            answer = "😵 AI 腦子轉不動了，稍後再試試～"
        _memory.record("小花" if m_xh else "機器人", answer)
        reply(reply_token, answer)
        return True
    except Exception as exc:
        logger.exception("handle_ai_mention error: %s", exc)
        reply(reply_token, f"😵 小花這邊出了點狀況：{type(exc).__name__}，請稍後再試或叫姊姊來修我 🔧")
        return True



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


@app.route("/memory")
def memory_status():
    """Return current process memory usage (works on Linux/Render without psutil)."""
    import os
    data = {
        "rss_mb": None,
        "vmem_mb": None,
        "service": os.environ.get("RENDER_SERVICE_NAME", "line-family-bot"),
    }
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        data["rss_mb"] = round(int(parts[1]) / 1024, 2)
                elif line.startswith("VmSize:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        data["vmem_mb"] = round(int(parts[1]) / 1024, 2)
    except Exception:
        pass
    try:
        import psutil
        p = psutil.Process(os.getpid())
        info = p.memory_info()
        data["rss_mb"] = round(info.rss / 1024 / 1024, 2)
        data["vmem_mb"] = round(info.vms / 1024 / 1024, 2)
    except Exception:
        pass
    return data, 200




def _verify_signature(body: str, signature: str) -> bool:
    """Fast local signature check — no network, no exceptions."""
    secret = os.environ.get("LINE_CHANNEL_SECRET", "")
    if not secret or not signature:
        return False
    expected = base64.b64encode(
        hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    ).decode()
    return hmac.compare_digest(signature, expected)


def _dispatch_webhook(body: str, signature: str):
    """Process webhook events in a background thread."""
    try:
        handler.handle(body, signature)
    except Exception as exc:
        logger.error("Webhook processing error: %s", exc)
        from utils import send_telegram_alert
        send_telegram_alert(f"webhook error: {type(exc).__name__}: {str(exc)[:200]}")


@app.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)

    # Fast local signature verification — return 400 before doing anything else
    if not _verify_signature(body, signature):
        return "Invalid signature", 400

    # Deduplication: skip duplicate webhook deliveries
    from tts_store import webhook_seen
    dedup_key = hashlib.sha256(body.encode()).hexdigest()[:32]
    if webhook_seen(dedup_key, ttl_seconds=60):
        return "OK", 200

    # Return 200 immediately so LINE doesn't time out (reply token = 30s)
    # Process in bounded thread pool (max 8 workers) to prevent memory blow-up
    _webhook_pool.submit(_dispatch_webhook, body, signature)
    return "OK"

def _safe_handle_fun(reply_token, source, text, member):
    try:
        return handle_fun(reply_token, source, text, member)
    except Exception as exc:
        _grp = os.environ.get("LINE_GROUP_ID", "")
        if _grp:
            push_messages(_grp, [{"type": "text", "text": f"[D_ERR] handle_fun crash: {type(exc).__name__}: {str(exc)[:100]}"}])
        return False


def _process_text_message(reply_token: str, text: str, source, member: str = "") -> bool:
    """處理文字訊息的核心邏輯（文字/語音轉文字共用）。回傳 True 表示已由指令處理。"""
    try:
        # ── 待辦提醒 ──
        if text.startswith("提醒"):
            reply(reply_token, handle_add_todo(member, text))
            return True
        if text in ["待辦清單", "待辦", "我的待辦", "待辦事項"]:
            reply(reply_token, handle_view_todos())
            return True
        if text.startswith("完成待辦"):
            result = handle_complete_todo(member, text)
            if result:
                reply(reply_token, result)
                return True
        if text.startswith("取消待辦"):
            result = handle_cancel_todo(member, text)
            if result:
                reply(reply_token, result)
                return True

        from handlers.books import handle_book_command
        if handle_book_command(reply_token, text, member):
            return True
        if handle_admin(reply_token, source, text):
            return True
        if handle_batch_log(reply_token, member, text):
            return True
        if handle_help(reply_token, text):
            return True
        if handle_chores(reply_token, member, text):
            return True
        if handle_points(reply_token, member, text):
            return True
        if handle_shopping(reply_token, member, text):
            return True
        if handle_accounting(reply_token, member, text):
            return True
        if handle_fine(reply_token, member, text):
            return True
        if handle_declutter(reply_token, member, text):
            return True
        if handle_tea(reply_token, member, text):
            return True
        from handlers.notebook import handle_notebook_command
        if handle_notebook_command(reply_token, text, member, reply):
            return True
        from handlers.links import handle_link_command
        if handle_link_command(reply_token, text, member, reply):
            return True
        if _safe_handle_fun(reply_token, source, text, member):
            return True
        if handle_ai_mention(reply_token, text, member):
            return True

        # 拼字容錯：短指令找最接近的
        _KNOWN_COMMANDS = [
            "家事清單", "點數", "我的點數", "購物清單", "帳目", "欠款",
            "天氣", "今天吃什麼", "星座", "今日全員運勢", "笑話", "冷知識",
            "今日宇宙", "推薦電影", "新聞", "今日新聞", "金價", "激勵名言",
            "今日日文單字", "今日西文單字", "今日漢字", "說明", "指令清單",
            "今天做什麼", "今天運動", "動漫名言", "出題", "翻譯",
            "待辦清單", "我的待辦", "完成待辦",
        ]
        if len(text) <= 8 and not re.search(r"[a-zA-Z0-9]", text):
            close = difflib.get_close_matches(text, _KNOWN_COMMANDS, n=1, cutoff=0.6)
            if close:
                reply(reply_token, f"你是想說「{close[0]}」嗎？試試傳那個指令 😊")
                return True

    except Exception as exc:
        logger.exception("_process_text_message error: %s", exc)
        try:
            from utils import send_telegram_alert
            send_telegram_alert(f"_process_text_message {type(exc).__name__}: {exc}\ntext={text[:80]!r}")
        except Exception:
            pass
        reply(reply_token, "😵 哎呀，我剛剛當機一下！稍後再試試，或是叫可愛的姊姊來修我 🔧")
        return True

    return False


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event: MessageEvent):
    if not hasattr(event, "reply_token") or not event.reply_token:
        return

    text = event.message.text.strip()
    reply_token = event.reply_token

    user_id = ""
    if hasattr(event, "source") and hasattr(event.source, "user_id"):
        user_id = event.source.user_id

    # 設定群組 context（記憶體隔離）
    group_id = (
        getattr(event.source, "group_id", None)
        or getattr(event.source, "room_id", None)
        or f"dm_{user_id}"
    )
    _memory.set_context(group_id)

    # Rate limiting (30 requests / 60s per user)
    if user_id and not rate_limit_check(user_id, max_requests=30, window_seconds=60):
        reply(reply_token, "⏳ 你發太快了，請稍後再試 👋")
        return

    member = resolve_member(user_id) if user_id else ""

    _grp = os.environ.get("LINE_GROUP_ID", "")
    _has_mention = bool(hasattr(event.message, "mention") and event.message.mention)

    # 小花快捷路徑（暫時繞過 _process_text_message 除錯）
    if text.startswith("小花") and not _has_mention:
        _xiaohua_answer = ""
        try:
            question = text[2:].strip()
            logger.info("[小花快捷路徑] question=%r member=%r", question, member)
            if question:
                # 提醒指令路由到 todo handler
                if question.startswith("提醒"):
                    from handlers.todos import handle_add_todo
                    _xiaohua_answer = handle_add_todo(member, question)
                    _real_group_id = getattr(event.source, "group_id", None) or getattr(event.source, "room_id", None)
                    target_id = _real_group_id or _grp or user_id
                    push_messages(target_id, [{"type": "text", "text": _xiaohua_answer}])
                    return
                persona = (
                    "你叫小花，是這個家的AI助手，個性溫柔但偶爾小毒舌。用繁體中文回答，簡短有趣。"
                    "重要：絕對不能捏造家事點數、待辦事項等資料庫的實際數字。"
                    "若有人要你幫忙加點數，請告知正確指令（如：完成 拖地）。"
                )
                if _should_inject_kb(question):
                    from handlers.books import find_relevant_context as _kb_context
                    kb = _kb_context(question)
                else:
                    kb = ""
                full_prompt = persona + (f"\n\n{kb}\n\n---" if kb else "") + f"\n\n{member or '家人'}：{question}"
                _xiaohua_answer = call_ai(full_prompt) or "😵 腦子轉不動了～"
            else:
                _xiaohua_answer = "叫我？🌸 說吧！"
            logger.info("[小花快捷路徑] answer=%r", _xiaohua_answer[:50])
        except Exception as exc:
            logger.exception("[小花快捷路徑] error: %s", exc)
            _xiaohua_answer = f"😵 小花這邊出了點狀況：{type(exc).__name__}，請稍後再試 🔧"

        # 直接使用 push（reply 在 Render 上會不明原因 hang 住）
        _real_group_id = getattr(event.source, "group_id", None) or getattr(event.source, "room_id", None)
        target_id = _real_group_id or _grp or user_id
        logger.info("[小花快捷路徑] pushing to target_id=%s", target_id)
        try:
            push_messages(target_id, [{"type": "text", "text": _xiaohua_answer}])
            logger.info("[小花快捷路徑] push sent to %s", target_id)
        except Exception as exc:
            logger.error("[小花快捷路徑] push failed: %s", exc)
        return

    # 被 @ 提及時，先試指令，再 AI（Groq 優先）
    if hasattr(event.message, "mention") and event.message.mention:
        clean = re.sub(r"^@?\S+\s*", "", text).strip() or text
        _memory.record(member or "家人", clean)  # @提及一定是對話，直接記
        if not handle_fun(reply_token, event.source, clean, member):
            ctx = _memory.format_for_ai()
            if _should_inject_kb(clean):
                from handlers.books import find_relevant_context as _kb_context
                kb = _kb_context(clean)
            else:
                kb = ""
            prompt = (
                "你是一個溫暖實用的家庭助理，用繁體中文回答，簡潔不囉嗦。"
                + (f"\n\n{ctx}" if ctx else "")
                + (f"\n\n---\n\n{kb}\n\n---" if kb else "")
                + f"\n\n問題：{clean}"
            )
            answer = call_ai(prompt)
            _memory.record("機器人", answer)
            reply(reply_token, answer)
        return

    # 一般訊息：沒被指令處理才記（過濾掉「收拾 客廳」之類的命令）
    handled = _process_text_message(reply_token, text, event.source, member)
    if not handled:
        _memory.record(member or "家人", text)


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
    parsed = urlparse(audio_url)
    allowed_hosts = ("api-data.line.me", "data.line.me")
    if parsed.scheme != "https" or parsed.hostname not in allowed_hosts:
        reply(reply_token, "🎤 語音來源不合法")
        return

    # 下載音檔（限制 6MB，避免大檔案炸記憶體）
    _AUDIO_MAX_BYTES = 6 * 1024 * 1024
    try:
        r = requests.get(audio_url, timeout=15, allow_redirects=False, stream=True)
        r.raise_for_status()
        chunks = []
        total = 0
        for chunk in r.iter_content(65536):
            total += len(chunk)
            if total > _AUDIO_MAX_BYTES:
                reply(reply_token, "🎤 語音太長了，請傳短一點（6MB 以內）")
                return
            chunks.append(chunk)
        audio_bytes = b"".join(chunks)
        del chunks
    except Exception as e:
        reply(reply_token, f"🎤 語音下載失敗：{e}")
        return

    # ── 語音轉文字：Groq Whisper 優先，Gemini 作 fallback ──
    transcript = groq_stt(audio_bytes, "audio/mpeg")
    if transcript:
        del audio_bytes  # Groq succeeded; free raw audio early

    if not transcript and GEMINI_KEY:
        try:
            audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
            del audio_bytes  # free raw bytes; base64 copy is already made
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

    # 設定群組 context 和 member（要在 reply 前，確保記憶體記對群組）
    member = ""
    if hasattr(event, "source") and hasattr(event.source, "user_id"):
        member = resolve_member(event.source.user_id)

    group_id = (
        getattr(event.source, "group_id", None)
        or getattr(event.source, "room_id", None)
        or f"dm_{user_id}"
    )
    _memory.set_context(group_id)

    # 告訴使用者聽到了什麼（用 push 而非 reply，保留 reply_token 給指令回覆）
    heard_msg = f"🎤 聽到：「{transcript[:80]}{'...' if len(transcript) > 80 else ''}」"
    push_messages(group_id, [{"type": "text", "text": heard_msg}])

    _process_text_message(reply_token, transcript, event.source, member)


# ── 圖片訊息處理（只記錄 message ID，不自動分析，省錢）────────────────

_IMAGE_MAX_BYTES = 4 * 1024 * 1024  # 4MB limit for on-demand analysis


@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image_message(event: MessageEvent):
    """收到圖片時只把 message_id 存到 kv store，不主動呼叫 Gemini（省錢）。
    小花被呼叫且問題包含「圖」「看」時才分析。"""
    user_id = getattr(event.source, "user_id", "")
    member = resolve_member(user_id) if user_id else "家人"
    group_id = (
        getattr(event.source, "group_id", None)
        or getattr(event.source, "room_id", None)
        or f"dm_{user_id}"
    )
    _memory.set_context(group_id)
    # 存最近 3 張圖片的 message_id（TTL 6小時，LINE 媒體有效期內）
    from tts_store import kv_get, kv_set
    recent = kv_get(f"imgs:{group_id}", []) or []
    recent = ([{"id": event.message.id, "member": member}] + recent)[:3]
    kv_set(f"imgs:{group_id}", recent, ttl_seconds=21600)
    # 記入文字記憶（讓小花知道有圖被傳進來）
    _memory.record_ephemeral(member, "[傳了一張圖片]")


def _analyze_group_images(group_id: str) -> str:
    """拿最近存的圖片 ID → Gemini Vision 分析 → 回傳描述文字。限一次最多 1 張（省錢）。"""
    if not GEMINI_KEY:
        return ""
    from tts_store import kv_get
    recent = kv_get(f"imgs:{group_id}", []) or []
    if not recent:
        return ""
    img_info = recent[0]  # 最新一張
    try:
        img_resp = requests.get(
            f"https://api-data.line.me/v2/bot/message/{img_info['id']}/content",
            headers={"Authorization": f"Bearer {_token}"},
            timeout=15,
            stream=True,
        )
        img_resp.raise_for_status()
        chunks, total = [], 0
        for chunk in img_resp.iter_content(65536):
            total += len(chunk)
            if total > _IMAGE_MAX_BYTES:
                return ""
            chunks.append(chunk)
        image_bytes = b"".join(chunks)
        del chunks
        img_b64 = base64.b64encode(image_bytes).decode()
        del image_bytes
        url = (
            "https://generativelanguage.googleapis.com/v1beta/"
            f"models/gemini-2.5-flash-lite:generateContent?key={GEMINI_KEY}"
        )
        payload = {"contents": [{"parts": [
            {"text": "請用繁體中文描述這張圖片的內容（50字以內），直接描述重點。"},
            {"inline_data": {"mime_type": "image/jpeg", "data": img_b64}},
        ]}]}
        resp = requests.post(url, json=payload, timeout=20)
        del img_b64
        desc = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        return f"（{img_info.get('member', '家人')} 剛傳的圖：{desc}）"
    except Exception:
        return ""


from utils import send_telegram_alert, rate_limit_check

_webhook_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="wh")

@app.errorhandler(Exception)
def _handle_error(e):
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return e  # let Flask handle abort() normally
    import traceback
    err_msg = f"家管助理異常：{type(e).__name__}\n{str(e)[:200]}"
    logging.error("Unhandled exception: %s", err_msg)
    traceback.print_exc()
    send_telegram_alert(err_msg)
    return "Internal Server Error", 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, threaded=True)
