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
from linebot.v3.messaging import Configuration
from linebot.v3.webhooks import MessageEvent, TextMessageContent, AudioMessageContent
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
    m = re.match(r"^@?(?:機器人|家管|bot|助理|小花)\s*(.+)", text, re.IGNORECASE)
    if m:
        question = m.group(1).strip()
        # 先嘗試走指令處理（天氣、星座等）
        if handle_fun(reply_token, None, question):
            return True
        answer = call_ai(
            f"你是一個溫暖實用的家庭助理，用繁體中文回答，簡潔不囉嗦。\n\n問題：{question}"
        )
        reply(reply_token, answer)
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

    # Idempotency: atomically check-and-set
    from tts_store import cron_try_mark_done
    if not cron_try_mark_done("daily_push"):
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

    member = resolve_member(user_id) if user_id else ""

    # 被 @ 提及時，先試指令，再 AI（Groq 優先）
    if hasattr(event.message, "mention") and event.message.mention:
        clean = re.sub(r"^@?\S+\s*", "", text).strip() or text
        if not handle_fun(reply_token, event.source, clean, member):
            answer = call_ai(
                f"你是一個溫暖實用的家庭助理，用繁體中文回答，簡潔不囉嗦。\n\n問題：{clean}"
            )
            reply(reply_token, answer)
        return

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
        r = requests.get(audio_url, timeout=15, allow_redirects=False)
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

    # 告訴使用者聽到了什麼
    reply(reply_token, f"🎤 聽到：「{transcript[:80]}{'...' if len(transcript) > 80 else ''}」")

    # 繼續當作文本處理
    member = ""
    if hasattr(event, "source") and hasattr(event.source, "user_id"):
        member = resolve_member(event.source.user_id)

    _process_text_message(reply_token, transcript, event.source, member)


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
