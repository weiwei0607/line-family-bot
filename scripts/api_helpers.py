"""
API 工具集：天氣、AQI、星座、笑話、問答、飲料、運動、動漫、圖片生成、
匯率、金價、電影、串流平台、BMI、食物熱量、隨機活動、日文、西班牙文
"""

import os
import re
import html as _html
import random
import time

import io
import requests
from datetime import datetime, timedelta
from typing import Callable
import logging
logger = logging.getLogger(__name__)

LAT = float(os.environ.get("LOCATION_LAT", "25.04"))
LON = float(os.environ.get("LOCATION_LON", "121.53"))
WEATHER_CITY = os.environ.get("WEATHER_CITY", "Taipei")
APININJAS_KEY = os.environ.get("APININJAS_KEY", "")
NASA_KEY = os.environ.get("NASA_API_KEY", "")
TMDB_KEY = os.environ.get("TMDB_API_KEY", "")
ALPHA_VANTAGE_KEY = os.environ.get("ALPHA_VANTAGE_KEY", "")
PEXELS_KEY = os.environ.get("PEXELS_KEY", "")
NEWSAPI_KEY = os.environ.get("NEWSAPI_KEY", "")
ABSTRACT_KEY = os.environ.get("ABSTRACT_KEY", "")
GIPHY_KEY = os.environ.get("GIPHY_KEY", "")

QUOTA_MSG = "❌ 今日 API 額度用完了，明天再試試！"

# ─── Simple circuit breaker for API-Ninjas ────────────────
_CB_STATE = {"failures": 0, "open_until": 0.0}
_CB_THRESHOLD = 3
_CB_COOLDOWN = 300  # 5 minutes

def _cb_record(success: bool):
    if success:
        _CB_STATE["failures"] = 0
    else:
        _CB_STATE["failures"] += 1
        if _CB_STATE["failures"] >= _CB_THRESHOLD:
            _CB_STATE["open_until"] = time.time() + _CB_COOLDOWN

def _cb_is_open() -> bool:
    if time.time() < _CB_STATE["open_until"]:
        return True
    return False


def _check_quota(r) -> bool:
    return r.status_code == 429

def _apininjas_headers() -> dict:
    return {"X-Api-Key": APININJAS_KEY}

def _ninjas_get(path: str, **kwargs):
    """Wrapper for api.api-ninjas.com with circuit breaker."""
    if _cb_is_open():
        return None
    url = f"https://api.api-ninjas.com/v1{path}"
    try:
        r = _retry_http(lambda: requests.get(url, headers=_apininjas_headers(), timeout=10, **kwargs))
        if _check_quota(r):
            _cb_record(False)
            return None
        if not r.ok:
            _cb_record(False)
            return None
        _cb_record(True)
        return r
    except Exception:
        _cb_record(False)
        return None


def _gemini_key() -> str:
    return os.environ.get("GEMINI_API_KEY", "")


# ─── Prompt-injection guard ───────────────────────────────
from shared.security import sanitize_input


def call_groq(prompt: str) -> str:
    key = os.environ.get("GROQ_API_KEY", "")
    if not key:
        return ""
    prompt = sanitize_input(prompt)
    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 500,
            },
            timeout=10,
        )
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return ""


def groq_stt(audio_bytes: bytes, mime: str = "audio/mpeg") -> str:
    key = os.environ.get("GROQ_API_KEY", "")
    if not key:
        return ""
    try:
        ext = "mp3" if "mpeg" in mime else "m4a"
        resp = requests.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {key}"},
            files={"file": (f"audio.{ext}", io.BytesIO(audio_bytes), mime)},
            data={"model": "whisper-large-v3-turbo", "response_format": "text"},
            timeout=30,
        )
        return resp.text.strip() if resp.status_code == 200 else ""
    except Exception:
        return ""


from shared.retry import retry_http

def _retry_http(fn, max_retries=3, backoff=2):
    return retry_http(max_retries=max_retries, backoff=backoff)(fn)()


def call_ai(prompt: str) -> str:
    """Groq 優先，失敗或限速時 fallback 到 Gemini。"""
    try:
        result = call_groq(prompt)
        if result:
            return result
    except Exception:
        pass
    return call_gemini(prompt)


def call_gemini(prompt: str) -> str:
    key = _gemini_key()
    prompt = sanitize_input(prompt)
    if not key:
        return call_groq(prompt)
    try:
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={key}",
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=12,
        )
        if resp.status_code == 429:
            return call_groq(prompt)
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception:
        return call_groq(prompt)


# ── 快取機制（天氣 30 分鐘、星座 6 小時、新聞 1 小時）──

_cache: dict[str, tuple] = {}  # key -> (value, timestamp)
_CACHE_MAX = 200

def _cached(key: str, ttl: int, fn: Callable):
    now = time.time()
    entry = _cache.get(key)
    if entry and now - entry[1] < ttl:
        return entry[0]
    result = fn()
    if result:
        _cache[key] = (result, now)
        if len(_cache) > _CACHE_MAX:
            _cache.pop(next(iter(_cache)))
    return result


# ── WMO 天氣代碼 ──────────────────────────────────


# ── 天氣（Open-Meteo，無需 key，快取 30 分鐘）────────


# ── 人生建議（adviceslip，免費無需 key）───────────


# ── 冷知識（uselessfacts，免費無需 key）───────────


# ── 星座運勢（Aztro 免費，快取 6 小時）──────────────


# ── 笑話（API-Ninjas 直連）───────────────────────


# ── 問答題（API-Ninjas 直連）────────────────────


# ── 飲料食譜（API-Ninjas 直連）──────────────────


# ── 隨機活動（Bored API，免費無需 key）──────────


# ── 運動建議（API-Ninjas 直連）──────────────────


# ── 動漫名言（animechan.io，免費無需 key）──────────


# ── AI 圖片生成（Pollinations.ai，完全免費無需 key）


# ── 匯率（open.er-api.com，免費無需 key）──────────


# ── 金價（Yahoo Finance 非官方 API，免費無需 key）──


# ── 股票（Alpha Vantage，每天 25 次）────────────


# ── 幣價（CoinGecko，免費無需 key）──────────────


# ── 電影（TMDB）─────────────────────────────────


# ── 串流平台（TMDB watch/providers）──────────────


# ── BMI 計算（本地計算）──────────────────────────


# ── 食物熱量（API-Ninjas 直連）──────────────────


# ── 食譜搜尋（TheMealDB，免費無需 key）──────────


# ── Chuck Norris 笑話（免費無需 key）────────────


# ── 激勵名言（API-Ninjas 優先，fallback type.fit）


# ── 電影台詞（Gemini 負責）──────────────────────


# ── 天文冷知識（API-Ninjas 直連）────────────────


# ── 消耗熱量（API-Ninjas 直連）──────────────────


# ── 日文字典（Jisho，免費無需 key）──────────────


# ── 西班牙文字典（Free Dictionary API，免費無需 key）


# ── TheMealDB（免費無需 key）──────────────────────


# ── Open Trivia DB（免費無需 key）────────────────


# ── NumbersAPI（免費無需 key）────────────────────


# ── 翻譯（MyMemory 免費優先，失敗再用 Gemini）──────

_LANG_MAP = {
    "zh-TW": "zh-TW", "zh-CN": "zh-CN", "zh": "zh-TW",
    "ja": "ja-JP", "es": "es-ES", "en": "en-US",
    "ko": "ko-KR", "fr": "fr-FR", "de": "de-DE",
    "th": "th-TH", "vi": "vi-VN", "id": "id-ID",
}

_LANG_NAME = {
    "zh-TW": "繁體中文", "zh-CN": "簡體中文", "en": "英文",
    "ja": "日文", "ko": "韓文", "es": "西班牙文", "fr": "法文",
    "de": "德文", "th": "泰文", "vi": "越南文", "id": "印尼文",
}


def translate_text(text: str, target_lang: str = "zh-TW", source_lang: str = "auto") -> str:
    if not text:
        return text

    tgt = _LANG_MAP.get(target_lang, target_lang)
    src = "en" if source_lang == "auto" else source_lang

    # 1. MyMemory（完全免費，每天約 5000 次）
    try:
        r = requests.get(
            "https://api.mymemory.translated.net/get",
            params={"q": text[:500], "langpair": f"{src}|{tgt}"},
            timeout=8,
        )
        result = r.json().get("responseData", {}).get("translatedText", "")
        if result and result not in ("NO QUERY SPECIFIED", text) and not result.upper().startswith("PLEASE"):
            return result
    except Exception as _exc:
        logger.warning("API error: %s", _exc)

    # 2. Gemini fallback
    try:
        key = _gemini_key()
        if not key:
            return text
        lang_name = _LANG_NAME.get(target_lang, target_lang)
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={key}",
            json={"contents": [{"parts": [{"text": f"把以下文字翻譯成{lang_name}，只給翻譯結果，不要解釋：\n\n{text}"}]}]},
            timeout=15,
        )
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        return f"翻譯失敗：{e}"


# ── NASA APOD（每日天文圖片）──────────────────────

def get_nasa_apod() -> dict | None:
    def _fetch():
        key = NASA_KEY or "DEMO_KEY"
        for attempt in range(3):
            try:
                r = requests.get(
                    "https://api.nasa.gov/planetary/apod",
                    params={"api_key": key},
                    timeout=30 if attempt == 0 else 45,
                )
                if _check_quota(r):
                    return {"_quota": True}
                if r.status_code != 200:
                    return {"_error": f"NASA API 回傳 {r.status_code}，請稍後再試"}
                d = r.json()
                if d.get("error"):
                    return {"_error": f"NASA: {d.get('error', {}).get('message', '未知錯誤')}"}
                return {
                    "title": d.get("title", ""),
                    "date": d.get("date", ""),
                    "explanation": (d.get("explanation") or "")[:500],
                    "url": d.get("url", ""),
                    "hdurl": d.get("hdurl") or d.get("url", ""),
                    "media_type": d.get("media_type", "image"),
                }
            except requests.exceptions.Timeout:
                if attempt < 2:
                    time.sleep(2)
                    continue
                return {"_error": "NASA 伺服器回應較慢，請稍後再試 🌌"}
            except Exception as e:
                return {"_error": f"NASA 暫時無法連線：{e}"}
        return {"_error": "NASA 暫時無法連線，請稍後再試 🌌"}
    return _cached("nasa_apod", 43200, _fetch)


# ── 輪班工具 ─────────────────────────────────────

def _fallback_call(*callables: Callable):
    for fn in callables:
        try:
            result = fn()
            if result and (not isinstance(result, str) or result.strip()):
                return result
            if result and isinstance(result, dict) and result.get("error"):
                continue
            if result and isinstance(result, bytes) and len(result) > 100:
                return result
            if result:
                return result
        except Exception:
            continue
    return None


# ── TTS（edge-tts，免費 Microsoft 神經語音）──────────

_EDGE_TTS_VOICES = {
    "zh-TW": [
        "zh-TW-HsiaoChenNeural",   # 男，溫和沉穩
        "zh-TW-HsiaoYuNeural",     # 女，溫柔自然
    ],
    "zh-CN": ["zh-CN-XiaoxiaoNeural", "zh-CN-YunyangNeural"],
    "en": ["en-US-JennyNeural", "en-US-GuyNeural"],
    "ja": ["ja-JP-NanamiNeural"],
    "ko": ["ko-KR-SunHiNeural"],
}

def _detect_lang_char(char: str) -> str | None:
    """Detect language of a single character. Returns None for neutral chars."""
    if "\u3040" <= char <= "\u309f" or "\u30a0" <= char <= "\u30ff":
        return "ja"
    if "\uac00" <= char <= "\ud7a3":
        return "ko"
    if "\u4e00" <= char <= "\u9fff":
        return "zh-TW"
    return None


def _segment_by_lang(text: str) -> list[tuple[str, str]]:
    """Split text into segments by detected language.
    Non-CJK chars attach to the current segment."""
    segments = []
    current_lang = None
    current_text = []

    for char in text:
        lang = _detect_lang_char(char)
        if lang is None:
            # Non-CJK (English, numbers, punctuation, spaces) follow current segment
            lang = current_lang if current_lang else "en"

        if lang != current_lang and current_text:
            seg = "".join(current_text)
            if seg.strip():
                segments.append((current_lang, seg))
            current_text = []
        current_lang = lang
        current_text.append(char)

    if current_text:
        seg = "".join(current_text)
        if seg.strip():
            segments.append((current_lang, seg))

    return segments


def text_to_speech(text: str, lang: str = "zh-TW") -> tuple[bytes, str] | None:
    try:
        import asyncio
        import edge_tts

        segments = _segment_by_lang(text)
        if not segments:
            return None

        # 限制最多 2 段，避免 edge-tts 並發過多導致記憶體爆掉 (Render 512MB)
        if len(segments) > 2:
            # 超過 2 段時合併為 1 段，使用主語言語音
            merged_text = " ".join(seg for _, seg in segments)
            segments = [(lang, merged_text)]

        async def _synth_one(seg_text: str, seg_lang: str) -> bytes | None:
            voices = _EDGE_TTS_VOICES.get(seg_lang, _EDGE_TTS_VOICES.get(lang, ["zh-TW-HsiaoChenNeural"]))
            voice = random.choice(voices)
            communicate = edge_tts.Communicate(seg_text[:500], voice)
            buf = io.BytesIO()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    buf.write(chunk["data"])
            data = buf.getvalue()
            return data if len(data) > 100 else None

        async def _synth_all():
            parts = []
            for seg_lang, seg_text in segments:
                data = await _synth_one(seg_text, seg_lang)
                if data:
                    parts.append(data)
            return b"".join(parts) if parts else None

        audio_bytes = asyncio.run(_synth_all())
        if audio_bytes and len(audio_bytes) > 100:
            logger.info("TTS success: segments=%d text_len=%d bytes=%d", len(segments), len(text), len(audio_bytes))
            return audio_bytes, "audio/mpeg"
        logger.warning("TTS empty audio: segments=%d", len(segments))
        return None
    except Exception as exc:
        logger.warning("TTS failed: %s", exc)
        return None


# ── 翻譯快取（減少重複 API 呼叫）──────────────────

_TRANSLATE_CACHE: dict[tuple[str, str], tuple[str, float]] = {}
_TRANSLATE_CACHE_MAX = 500
_TRANSLATE_CACHE_TTL = 3600


def _translate_cache_get(text: str, target: str) -> str | None:
    key = (text.strip().lower(), target)
    entry = _TRANSLATE_CACHE.get(key)
    if entry and time.time() - entry[1] < _TRANSLATE_CACHE_TTL:
        return entry[0]
    return None


def _translate_cache_set(text: str, target: str, result: str):
    key = (text.strip().lower(), target)
    _TRANSLATE_CACHE[key] = (result, time.time())
    if len(_TRANSLATE_CACHE) > _TRANSLATE_CACHE_MAX:
        _TRANSLATE_CACHE.pop(next(iter(_TRANSLATE_CACHE)))


# ── 智慧翻譯（只翻英文，其他直接回傳）──────────

def smart_translate(text: str, target: str = "zh-TW") -> str:
    if not text or not text.strip():
        return text
    if any(ord(c) > 127 for c in text[:30]):
        return text
    cached = _translate_cache_get(text, target)
    if cached is not None:
        return cached
    result = translate_text(text, target)
    _translate_cache_set(text, target, result)
    return result


# ── 笑話輪班（API-Ninjas → JokeAPI.dev → Chuck Norris）


# ── Rewriter（RapidAPI）─────────────────────────────

def rewrite_text(text: str, strength: int = 3) -> str:
    """改寫/潤稿文字"""
    key = os.environ.get("RAPIDAPI_KEY", "")
    if not key:
        return ""
    try:
        r = requests.post(
            "https://rewriter-paraphraser-text-changer-multi-language.p.rapidapi.com/rewrite",
            headers={"x-rapidapi-key": key, "x-rapidapi-host": "rewriter-paraphraser-text-changer-multi-language.p.rapidapi.com", "Content-Type": "application/json"},
            json={"language": "zh-tw", "strength": strength, "text": text},
            timeout=10,
        )
        if r.status_code == 200:
            return r.json().get("rewrite", "")
    except Exception as _exc:
        logger.warning("API error: %s", _exc)
    return ""


# ── TextGears 英文文法檢查（RapidAPI）─────────────

def check_grammar(text: str) -> dict | None:
    """檢查英文文法，回傳 {corrected, errors}"""
    key = os.environ.get("RAPIDAPI_KEY", "")
    if not key:
        return None
    try:
        r = requests.post(
            "https://textgears-textgears-v1.p.rapidapi.com/correct",
            headers={"x-rapidapi-key": key, "x-rapidapi-host": "textgears-textgears-v1.p.rapidapi.com", "Content-Type": "application/x-www-form-urlencoded"},
            data=f"text={requests.utils.quote(text)}&language=en-US",
            timeout=10,
        )
        if r.status_code == 200:
            d = r.json()
            if d.get("status"):
                resp = d.get("response", {})
                corrected = resp.get("corrected", "")
                errors = resp.get("errors", [])
                return {"corrected": corrected, "errors": errors, "original": text}
    except Exception as _exc:
        logger.warning("API error: %s", _exc)
    return None


# ── Hotels Com 找飯店（RapidAPI）───────────────────


# ── World Airports 找機場（RapidAPI）───────────────


# ── 星座輪班（Aztro → Gemini，快取 6 小時）──────


# ── 星座配對（Gemini）────────────────────────────


# ── 圖片搜尋（Pexels，200 req/hour）────────────


# ── GIF（GIPHY，100 req/hour）───────────────────

def search_gif(query: str) -> dict | None:
    if not GIPHY_KEY:
        return None
    try:
        r = requests.get(
            "https://api.giphy.com/v1/gifs/search",
            params={"api_key": GIPHY_KEY, "q": query, "limit": 5, "rating": "g"},
            timeout=10,
        )
        data = r.json().get("data", [])
        if not data:
            return None
        gif = random.choice(data[:5])
        images = gif.get("images", {})
        return {
            "gif_url": images.get("original", {}).get("url", ""),
            "still_url": images.get("original_still", {}).get("url", ""),
        }
    except Exception as e:
        logger.warning("[giphy] %s", e)
    return None


def get_trending_gif() -> dict | None:
    if not GIPHY_KEY:
        return None
    def _fetch():
        try:
            r = requests.get(
                "https://api.giphy.com/v1/gifs/trending",
                params={"api_key": GIPHY_KEY, "limit": 10, "rating": "g"},
                timeout=10,
            )
            data = r.json().get("data", [])
            if not data:
                return None
            gif = random.choice(data[:10])
            images = gif.get("images", {})
            return {
                "gif_url": images.get("original", {}).get("url", ""),
                "still_url": images.get("original_still", {}).get("url", ""),
            }
        except Exception as e:
            logger.warning("[giphy trending] %s", e)
        return None
    return _cached("giphy_trending", 1800, _fetch)


# ── 新聞（NewsAPI 優先，fallback Google RSS，快取 1 小時）


# ── 節假日（Abstract API，每月 1000 次）─────────


# ── 維基百科（中文 Wikipedia API，免費無需 key）──


# ── QR Code（api.qrserver.com，免費無需 key）────


# ── 貓咪圖片（The Cat API，免費無需 key）────────


# ── 狗狗圖片（Dog CEO API，免費無需 key）────────


# ── 世界時間（WorldTimeAPI，免費無需 key）────────


# ── 國家資訊（RestCountries，免費無需 key）──────


# ── TTS 音檔暫存管理 ─────────────────────────────

_TTS_DIR = "/tmp/tts_files"
os.makedirs(_TTS_DIR, exist_ok=True)

def save_tts_audio(audio_bytes: bytes, mime_type: str = "audio/mpeg") -> str:
    fname = f"tts_{int(time.time()*1000)}.m4a"
    # Save to filesystem (fast serve) AND SQLite (survives restarts)
    with open(os.path.join(_TTS_DIR, fname), "wb") as f:
        f.write(audio_bytes)
    try:
        from tts_store import save_tts_audio as _db_save
        _db_save(fname, audio_bytes, mime_type)
    except Exception as _exc:
        logger.warning("API error: %s", _exc)
    # 只保留最新 50 個檔案
    files = sorted(
        [fn for fn in os.listdir(_TTS_DIR) if fn.startswith("tts_")],
        key=lambda fn: os.path.getmtime(os.path.join(_TTS_DIR, fn)),
    )
    for old in files[:-50]:
        try:
            os.remove(os.path.join(_TTS_DIR, old))
        except OSError:
            pass
    return fname

def get_tts_audio(filename: str) -> tuple[bytes, str] | None:
    # 1) Try filesystem first (fastest)
    path = os.path.join(_TTS_DIR, filename)
    if os.path.exists(path):
        with open(path, "rb") as f:
            return f.read(), "audio/mpeg"
    # 2) Fallback to SQLite (survives Render restarts)
    try:
        from tts_store import get_tts_audio as _db_get
        data = _db_get(filename)
        if data:
            return data
    except Exception as _exc:
        logger.warning("API error: %s", _exc)
    return None

# ── YouTube 搜尋（RapidAPI）───────────────────────

def fetch_youtube(query: str) -> str:
    """搜尋 YouTube 影片，回傳格式化的文字結果。"""
    key = os.environ.get("RAPIDAPI_KEY", "")
    if not key:
        return "需要設定 RAPIDAPI_KEY 才能搜尋影片"
    try:
        r = requests.get(
            "https://youtube-v31.p.rapidapi.com/search",
            headers={"x-rapidapi-key": key, "x-rapidapi-host": "youtube-v31.p.rapidapi.com"},
            params={"q": query, "part": "snippet", "type": "video", "maxResults": "3", "regionCode": "TW"},
            timeout=10,
        )
        if r.status_code == 200:
            d = r.json()
            items = d.get("items", [])
            if not items:
                return f"🎬 找不到「{query}」相關影片"
            lines = [f"🎬 找到以下影片：\n"]
            for item in items[:3]:
                snippet = item.get("snippet", {})
                vid_id = item.get("id", {}).get("videoId", "")
                title = snippet.get("title", "")
                channel = snippet.get("channelTitle", "")
                if vid_id:
                    lines.append(f"• {title}\n  {channel}\n  https://youtu.be/{vid_id}")
            return "\n".join(lines)
    except Exception as _exc:
        logger.warning("fetch_youtube error: %s", _exc)
    return f"🎬 搜尋「{query}」失敗，待會再試"


# ─── Lazy imports for cold-start optimization ─────────────
_LAZY_SUBMODULES = [
    "weather_api", "entertainment_api", "finance_api",
    "health_api", "language_api", "travel_api",
]


def __getattr__(name: str):
    """Lazy-load functions from split submodules to speed up cold starts."""
    for mod in _LAZY_SUBMODULES:
        try:
            submodule = __import__(mod, globals(), locals(), [name])
            val = getattr(submodule, name, None)
            if val is not None:
                globals()[name] = val
                return val
        except (ImportError, AttributeError):
            pass
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
