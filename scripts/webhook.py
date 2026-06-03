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

from handlers import (
    _handle_entertainment,
    _handle_finance,
    _handle_horoscope,
    _handle_images,
    _handle_language,
    _handle_quiz,
    _handle_tidy,
    _handle_tts,
    _handle_utils,
    _handle_weather,
    handle_admin,
    handle_batch_log,
    handle_chores,
    handle_declutter,
    handle_fine,
    handle_help,
    handle_points,
    handle_shopping,
    handle_accounting,
    resolve_member,
)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024  # 2MB max payload

import memory as _memory
from sheets import bg as _bg
_bg(_memory.load_from_sheets)  # 啟動時從 Sheets 還原對話歷史

# 包裝 reply，讓機器人回覆自動記入短暫記憶（跳過錯誤訊息）
_ERROR_PREFIXES = ("❌", "⚠️", "⏳", "🚫")
_raw_reply = reply
def reply(token: str, text: str, **kw):
    if text and not text.startswith(_ERROR_PREFIXES):
        _memory.record_ephemeral("機器人", text)
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



def handle_fun(reply_token: str, source, text: str, member: str = "") -> bool:

    group_id = getattr(source, "group_id", None) or getattr(source, "room_id", "default")

    # ── 收拾紀錄（優先於小白，避免「收拾清單」被集塵盒關鍵字攔截）──
    if _handle_tidy(reply_token, text, member, source, configuration):
        return True

    # ── 小白（掃地機器人）維護紀錄 ──
    from vacuum_tracker import handle as vacuum_handle
    reply_text = vacuum_handle(text, user=member or "家人")
    if reply_text:
        reply(reply_token, reply_text)
        return True

    # ── Simple dispatch (fast path for stateless commands) ──
    from dispatch_fun import try_dispatch
    if try_dispatch(text, lambda t: reply(reply_token, t)):
        return True

    # ── 趣味互動（骰子、猜拳、配對）──
    from handlers.games import handle_pairing, handle_dice, handle_rps
    if text.startswith("配對"):
        reply(reply_token, handle_pairing(text))
        return True
    if re.search(r'搖骰子|擲骰子|搖\d*[顆個]骰', text):
        reply(reply_token, handle_dice(text))
        return True
    if text.startswith("猜拳"):
        reply(reply_token, handle_rps(text))
        return True

    # ── 投票 ──
    from handlers.vote import handle_vote
    vote_result = handle_vote(text, group_id, member)
    if vote_result is not None:
        reply(reply_token, vote_result)
        return True

    # ── 天氣 ──
    if _handle_weather(reply_token, text):
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


_IS_XIAOHUA = re.compile(r"^@?小花\s*(.+)", re.IGNORECASE)
_IS_BOT     = re.compile(r"^@?(?:機器人|家管|bot|助理)\s*(.+)", re.IGNORECASE)

def handle_ai_mention(reply_token: str, text: str, member: str = ""):
    """@小花 / @機器人 問問題（純文字觸發，非 LINE 正式 mention）"""
    m_xh = _IS_XIAOHUA.match(text)
    m_bot = _IS_BOT.match(text)
    m = m_xh or m_bot
    if not m:
        return False

    question = m.group(1).strip()
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

    prompt = (
        persona
        + (f"\n\n{ctx}" if ctx else "")
        + (f"\n\n{img_desc}" if img_desc else "")
        + f"\n\n{member or '家人'}：{question}"
    )
    answer = call_ai(prompt)
    _memory.record("小花" if m_xh else "機器人", answer)
    reply(reply_token, answer)
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


@app.route("/daily_push", methods=["POST"])
def daily_push():
    """早安推播（含 TTS），由 GitHub Actions 每天呼叫"""
    cron_secret = os.environ.get("CRON_SECRET", "")
    token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    if not cron_secret or not token or token != cron_secret:
        abort(403)

    from sheets import get_members, get_chores, get_weekly_points
    from api_helpers import format_weather_block

    group_id = os.environ.get("LINE_GROUP_ID", "")
    if not group_id:
        return "LINE_GROUP_ID not set", 500

    # ── 先準備內容、推送訊息，最後才標記 done（避免冷啟動超時導致「標了沒發」）──
    try:
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
                lines.append(f"  {m}：目前 {round(pts.get(m,0), 1):g} 點（目標 {POINTS_THRESHOLD} 點）")
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

    except Exception as exc:
        logger.exception("daily_push failed: %s", exc)
        try:
            from utils import send_telegram_alert
            send_telegram_alert(f"daily_push failed: {type(exc).__name__}: {exc}")
        except Exception:
            pass
        return f"Error: {exc}", 500

    # 推送成功後才標記 done
    from tts_store import cron_try_mark_done
    cron_try_mark_done("daily_push")
    return "OK"


@app.route("/check_reminders", methods=["POST"])
def check_reminders():
    """連環扣提醒：由 GitHub Actions 每 10 分鐘呼叫一次。"""
    cron_secret = os.environ.get("CRON_SECRET", "")
    token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    if not cron_secret or not token or token != cron_secret:
        abort(403)

    from sheets import get_todos, update_todo_reminder
    from datetime import datetime as _dt, timedelta as _td
    from sheets import TW_TZ

    group_id = os.environ.get("LINE_GROUP_ID", "")
    if not group_id:
        return "LINE_GROUP_ID not set", 500

    now = _dt.now(TW_TZ)
    today = now.strftime("%Y-%m-%d")
    todos = get_todos(only_pending=True)

    base_url = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
    sent = 0

    def _push_with_tts(msg, voice_text):
        nonlocal sent
        push_messages(group_id, [{"type": "text", "text": msg}])
        if base_url:
            tts_result = text_to_speech(voice_text, "zh-TW")
            if tts_result:
                audio_bytes, mime = tts_result
                fname = save_tts_audio(audio_bytes, mime)
                audio_url = f"{base_url}/tts/{fname}"
                duration = min(len(voice_text) * 300 + 1000, 30000)
                push_messages(group_id, [{"type": "audio", "originalContentUrl": audio_url, "duration": duration}])
        sent += 1

    def _send_reminder(t, msg, voice_text, new_count):
        _push_with_tts(msg, voice_text)
        update_todo_reminder(t["row"], new_count)

    for t in todos:
        try:
            if t["date"] != today:
                continue
            time_str = t.get("time", "").strip()
            reminded = t.get("reminded_count", 0)
            member = t["member"]
            content = t["content"]
            created_by = t.get("created_by", "")
            voice_content = content.replace("我", created_by) if created_by else content

            if time_str:
                # ── 有時間：奪命連環扣（最多 3 次）──
                if reminded >= 3:
                    continue
                try:
                    todo_hour, todo_min = int(time_str[:2]), int(time_str[3:5])
                except (ValueError, IndexError):
                    continue
                due = _dt(now.year, now.month, now.day, todo_hour, todo_min, tzinfo=TW_TZ)
                # Skip if due time was more than 1 hour ago and never reminded (stale)
                if reminded == 0 and now > due + _td(hours=1):
                    continue
                trigger = due + _td(minutes=30 * reminded)
                if now < trigger:
                    continue

                if reminded == 0:
                    msg = f"🔔 提醒時間到！\n📌 {member}：{content}\n\n完成後傳「完成待辦 {content[:10]}」，否則 30 分鐘後會繼續叫你 😤"
                    voice_text = f"提醒時間到！{member}，{voice_content}！"
                else:
                    bells = "🔔" * (reminded + 1)
                    remaining = 3 - reminded - 1
                    suffix = f"（還差 {remaining} 次就放棄了）" if remaining > 0 else "（最後一次了，拜託快去做！）"
                    msg = f"{bells} 還沒做喔！\n📌 {member}：{content}\n完成後傳「完成待辦 {content[:10]}」{suffix}"
                    voice_text = f"{member}，{voice_content}還沒完成喔！快去做！"
                _send_reminder(t, msg, voice_text, reminded + 1)
            else:
                # ── 沒時間：晚上 20:00 提醒一次（不連環扣）──
                if reminded >= 1:
                    continue
                if now.hour < 20:
                    continue
                msg = f"🔔 今日待辦提醒！\n📌 {member}：{content}"
                voice_text = f"今日待辦提醒！{member}，{voice_content}！"
                _send_reminder(t, msg, voice_text, 1)
        except Exception as _e:
            logger.warning("check_reminders: error processing todo row %s: %s", t.get("row"), _e)

    # ── 前一天晚上提醒（20:00+，每筆只推一次，用 kv 去重）──
    if now.hour >= 20:
        from tts_store import kv_get as _kv_get, kv_set as _kv_set
        tomorrow = (now + _td(days=1)).strftime("%Y-%m-%d")
        for t in todos:
            try:
                if t["date"] != tomorrow:
                    continue
                preday_key = f"preday:{t['date']}:{t['member']}:{t['content'][:20]}"
                if _kv_get(preday_key):
                    continue
                member = t["member"]
                content = t["content"]
                created_by = t.get("created_by", "")
                voice_content = content.replace("我", created_by) if created_by else content
                msg = f"📅 明天待辦提醒！\n📌 {member}：{content}\n\n完成後傳「完成待辦 {content[:10]}」"
                voice_text = f"提醒一下！{member}，明天要{voice_content}！"
                _push_with_tts(msg, voice_text)
                _kv_set(preday_key, "1", ttl_seconds=90000)  # ~25h，避免隔天又推
            except Exception as _e:
                logger.warning("check_reminders: error processing pre-day todo row %s: %s", t.get("row"), _e)

    return f"sent {sent} reminders", 200


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

def _process_text_message(reply_token: str, text: str, source, member: str = "") -> bool:
    """處理文字訊息的核心邏輯（文字/語音轉文字共用）。回傳 True 表示已由指令處理。"""
    try:
        # ── 待辦提醒 ──
        from handlers.todos import handle_add_todo, handle_view_todos, handle_complete_todo, handle_cancel_todo
        if text.startswith("提醒"):
            reply(reply_token, handle_add_todo(member, text))
            return True
        if text in ["待辦清單", "待辦", "我的待辦"]:
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
            handle_ai_mention(reply_token, text, member)
        ):
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

    # 被 @ 提及時，先試指令，再 AI（Groq 優先）
    if hasattr(event.message, "mention") and event.message.mention:
        clean = re.sub(r"^@?\S+\s*", "", text).strip() or text
        _memory.record(member or "家人", clean)  # @提及一定是對話，直接記
        if not handle_fun(reply_token, event.source, clean, member):
            ctx = _memory.format_for_ai()
            prompt = (
                "你是一個溫暖實用的家庭助理，用繁體中文回答，簡潔不囉嗦。"
                + (f"\n\n{ctx}" if ctx else "")
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
    from urllib.parse import urlparse
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
            import base64
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

_webhook_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="wh")

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
