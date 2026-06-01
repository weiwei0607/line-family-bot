"""
API 工具集：天氣、AQI、星座、笑話、問答、飲料、運動、動漫、圖片生成、
匯率、金價、電影、串流平台、BMI、食物熱量、隨機活動、日文、西班牙文
"""

import os
import html as _html
import random
import time
import io
import requests
from typing import Callable

LAT = float(os.environ.get("LOCATION_LAT", "25.04"))
LON = float(os.environ.get("LOCATION_LON", "121.53"))
WEATHER_CITY = os.environ.get("WEATHER_CITY", "Taipei")
APININJAS_KEY = os.environ.get("APININJAS_KEY", "")
NASA_KEY = os.environ.get("NASA_API_KEY", "")
TMDB_KEY = os.environ.get("TMDB_API_KEY", "")

QUOTA_MSG = "❌ 今日 API 額度用完了，明天再試試！"

def _check_quota(r) -> bool:
    return r.status_code == 429

def _apininjas_headers() -> dict:
    return {"X-Api-Key": APININJAS_KEY}

def _gemini_key() -> str:
    return os.environ.get("GEMINI_API_KEY", "")

def call_gemini(prompt: str) -> str:
    key = _gemini_key()
    if not key:
        return ""
    try:
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={key}",
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=15,
        )
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception:
        return ""


# ── 快取機制（天氣 30 分鐘、星座 6 小時、新聞 1 小時）──

_cache: dict[str, tuple] = {}  # key -> (value, timestamp)

def _cached(key: str, ttl: int, fn: Callable):
    entry = _cache.get(key)
    if entry and time.time() - entry[1] < ttl:
        return entry[0]
    result = fn()
    if result:
        _cache[key] = (result, time.time())
    return result


# ── WMO 天氣代碼 ──────────────────────────────────

WMO = {
    0: "☀️ 晴天", 1: "🌤 大致晴", 2: "⛅️ 部分多雲", 3: "☁️ 陰天",
    45: "🌫 有霧", 48: "🌫 有霧",
    51: "🌦 毛毛雨", 53: "🌦 毛毛雨", 55: "🌧 小雨",
    61: "🌧 小雨", 63: "🌧 中雨", 65: "🌧 大雨",
    71: "🌨 小雪", 73: "🌨 中雪", 75: "❄️ 大雪",
    80: "🌦 陣雨", 81: "🌧 陣雨", 82: "⛈ 大陣雨",
    95: "⛈ 雷雨", 96: "⛈ 雷雨夾冰雹", 99: "⛈ 雷雨夾冰雹",
}

SIGN_MAP = {
    "牡羊": "aries", "金牛": "taurus", "雙子": "gemini", "巨蟹": "cancer",
    "獅子": "leo", "處女": "virgo", "天秤": "libra", "天蠍": "scorpio",
    "射手": "sagittarius", "摩羯": "capricorn", "水瓶": "aquarius", "雙魚": "pisces",
}

CURRENCY_MAP = {
    "美金": "USD", "美元": "USD", "日圓": "JPY", "日幣": "JPY",
    "歐元": "EUR", "英鎊": "GBP", "韓元": "KRW", "韓幣": "KRW",
    "人民幣": "CNY", "港幣": "HKD", "澳幣": "AUD", "加幣": "CAD",
}


# ── 天氣（Open-Meteo，無需 key，快取 30 分鐘）────────

def get_weather() -> dict:
    def _fetch():
        try:
            r = requests.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": LAT, "longitude": LON,
                    "current": "temperature_2m,weathercode,relative_humidity_2m",
                    "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                    "timezone": "Asia/Taipei", "forecast_days": 1,
                },
                timeout=10,
            )
            d = r.json()
            cur, day = d["current"], d["daily"]
            code = int(cur.get("weathercode", 0))
            return {
                "condition": WMO.get(code, "天氣不明"),
                "temp": round(cur["temperature_2m"]),
                "humidity": round(cur["relative_humidity_2m"]),
                "temp_max": round(day["temperature_2m_max"][0]),
                "temp_min": round(day["temperature_2m_min"][0]),
                "rain_prob": round(day["precipitation_probability_max"][0]),
            }
        except Exception as e:
            return {"error": str(e)}
    return _cached("weather", 1800, _fetch) or {"error": "無法取得天氣"}


def get_aqi() -> dict:
    def _fetch():
        try:
            r = requests.get(
                "https://air-quality-api.open-meteo.com/v1/air-quality",
                params={"latitude": LAT, "longitude": LON, "current": "us_aqi,pm2_5"},
                timeout=10,
            )
            d = r.json()["current"]
            aqi = round(d["us_aqi"])
            pm25 = round(d["pm2_5"], 1)
            level = ("良好 😊" if aqi <= 50 else "普通 😐" if aqi <= 100
                     else "對敏感族群不健康 😷" if aqi <= 150 else "不健康 ⚠️")
            return {"aqi": aqi, "pm25": pm25, "level": level}
        except Exception as e:
            return {"error": str(e)}
    return _cached("aqi", 1800, _fetch) or {"error": "無法取得 AQI"}


def format_weather_block() -> str:
    w = get_weather()
    if "error" in w:
        return "（天氣資料取得失敗）"
    a = get_aqi()
    lines = [
        f"{w['condition']}　{w['temp']}°C",
        f"最高 {w['temp_max']}° / 最低 {w['temp_min']}°　降雨機率 {w['rain_prob']}%",
        f"濕度 {w['humidity']}%",
    ]
    if "error" not in a:
        lines.append(f"空氣品質 AQI {a['aqi']}（{a['level']}）PM2.5：{a['pm25']}")
    return "\n".join(lines)


# ── 人生建議（adviceslip，免費無需 key）───────────

def get_advice() -> str:
    try:
        r = requests.get("https://api.adviceslip.com/advice", timeout=5)
        return r.json()["slip"]["advice"]
    except Exception:
        return ""


# ── 冷知識（uselessfacts，免費無需 key）───────────

def get_fun_fact() -> str:
    try:
        r = requests.get(
            "https://uselessfacts.jsph.pl/api/v2/facts/random",
            params={"language": "en"}, timeout=8,
        )
        return r.json().get("text", "")
    except Exception:
        return ""


# ── 星座運勢（Aztro，免費無需 key，快取 6 小時）───

def get_horoscope(sign_zh: str) -> dict | None:
    sign_zh = sign_zh.replace("座", "").strip()
    sign_en = SIGN_MAP.get(sign_zh)
    if not sign_en:
        return None
    def _fetch():
        try:
            r = requests.post(
                f"https://aztro.sameerkumar.website/?sign={sign_en}&day=today",
                timeout=10,
            )
            d = r.json()
            return {
                "sign": sign_zh + "座",
                "description": d.get("description", ""),
                "mood": d.get("mood", ""),
                "color": d.get("color", ""),
                "lucky_number": d.get("lucky_number", ""),
                "compatibility": d.get("compatibility", ""),
            }
        except Exception:
            return None
    return _cached(f"horoscope_{sign_en}", 21600, _fetch)


# ── 笑話（API-Ninjas 直連）───────────────────────

def get_joke() -> str:
    if not APININJAS_KEY:
        return ""
    try:
        r = requests.get("https://api.api-ninjas.com/v1/jokes",
                         headers=_apininjas_headers(), timeout=10)
        if _check_quota(r):
            return QUOTA_MSG
        items = r.json()
        return items[0].get("joke", "") if items else ""
    except Exception:
        return ""


# ── 問答題（API-Ninjas 直連）────────────────────

def get_trivia() -> dict | None:
    if not APININJAS_KEY:
        return None
    try:
        r = requests.get("https://api.api-ninjas.com/v1/trivia",
                         headers=_apininjas_headers(), timeout=10)
        if _check_quota(r):
            return {"_quota": True}
        items = r.json()
        return {"question": items[0].get("question", ""), "answer": items[0].get("answer", "")} if items else None
    except Exception:
        return None


# ── 飲料食譜（API-Ninjas 直連）──────────────────

def get_cocktail(name: str = "") -> dict | None:
    if not APININJAS_KEY:
        return None
    params = {"name": name if name else random.choice(["lemonade", "tea", "smoothie", "juice"])}
    try:
        r = requests.get("https://api.api-ninjas.com/v1/cocktail",
                         headers=_apininjas_headers(), params=params, timeout=10)
        if _check_quota(r):
            return {"_quota": True}
        items = r.json()
        return items[0] if items else None
    except Exception:
        return None


# ── 隨機活動（Bored API，免費無需 key）──────────

def get_random_activity() -> dict | None:
    try:
        r = requests.get("https://bored-api.appbrewery.com/random", timeout=10)
        d = r.json()
        return {"activity": d.get("activity", ""), "participants": d.get("participants", 1), "type": d.get("type", "")}
    except Exception:
        return None


# ── 運動建議（API-Ninjas 直連）──────────────────

def get_exercise() -> dict | None:
    if not APININJAS_KEY:
        return None
    try:
        muscles = ["biceps", "triceps", "chest", "back", "shoulders", "legs", "abs"]
        r = requests.get("https://api.api-ninjas.com/v1/exercises",
                         headers=_apininjas_headers(),
                         params={"muscle": random.choice(muscles)},
                         timeout=10)
        if not _check_quota(r):
            items = r.json()
            return items[0] if items else None
    except Exception:
        pass
    return None


# ── 動漫名言（animechan.io，免費無需 key）──────────

def get_anime_quote() -> dict | None:
    try:
        r = requests.get("https://animechan.io/api/v1/quotes/random", timeout=10)
        d = r.json().get("data", {})
        return {
            "quote": d.get("content", ""),
            "anime": d.get("anime", {}).get("name", "") if isinstance(d.get("anime"), dict) else "",
            "character": d.get("character", {}).get("name", "") if isinstance(d.get("character"), dict) else "",
        }
    except Exception:
        return None


# ── AI 圖片生成（Pollinations.ai，完全免費無需 key）

def generate_image(prompt: str) -> str | None:
    try:
        encoded = requests.utils.quote(prompt)
        url = f"https://image.pollinations.ai/prompt/{encoded}?width=512&height=512&nologo=true&seed={random.randint(1,9999)}"
        r = requests.head(url, timeout=25)
        return url if r.status_code == 200 else None
    except Exception:
        return None


# ── 匯率（frankfurter.app，免費無需 key）──────────

def get_currency(from_curr: str, to_curr: str = "TWD") -> dict | None:
    from_curr = CURRENCY_MAP.get(from_curr, from_curr.upper())
    to_curr = CURRENCY_MAP.get(to_curr, to_curr.upper())
    try:
        r = requests.get(
            "https://api.frankfurter.app/latest",
            params={"from": from_curr, "to": to_curr},
            timeout=10,
        )
        if r.status_code != 200:
            return None
        rate = r.json().get("rates", {}).get(to_curr)
        return {"from": from_curr, "to": to_curr, "rate": round(rate, 4)} if rate else None
    except Exception:
        return None


# ── 金價（Yahoo Finance 非官方 API，免費無需 key）──

def get_gold_price() -> dict | None:
    try:
        r = requests.get(
            "https://query1.finance.yahoo.com/v8/finance/chart/GC%3DF",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        price = r.json()["chart"]["result"][0]["meta"]["regularMarketPrice"]
        silver_r = requests.get(
            "https://query1.finance.yahoo.com/v8/finance/chart/SI%3DF",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        silver = silver_r.json()["chart"]["result"][0]["meta"]["regularMarketPrice"]
        return {"gold_usd": round(price, 2), "silver_usd": round(silver, 2)}
    except Exception:
        return None


# ── 電影（TMDB）─────────────────────────────────

def get_movie(title: str = "") -> dict | None:
    return get_tmdb_movie(title)


def get_tmdb_movie(title: str = "") -> dict | None:
    if not TMDB_KEY:
        return None
    try:
        if title:
            r = requests.get(
                "https://api.themoviedb.org/3/search/movie",
                params={"api_key": TMDB_KEY, "query": title, "language": "zh-TW", "region": "TW"},
                timeout=10,
            )
            if _check_quota(r):
                return {"_quota": True}
            results = r.json().get("results", [])
            movie = results[0] if results else None
        else:
            r = requests.get(
                "https://api.themoviedb.org/3/movie/popular",
                params={"api_key": TMDB_KEY, "language": "zh-TW", "region": "TW"},
                timeout=10,
            )
            if _check_quota(r):
                return {"_quota": True}
            results = r.json().get("results", [])
            movie = random.choice(results[:20]) if results else None
        if not movie:
            return None
        poster = f"https://image.tmdb.org/t/p/w500{movie['poster_path']}" if movie.get("poster_path") else None
        return {
            "id": movie.get("id"),
            "title": movie.get("title", ""),
            "original_title": movie.get("original_title", ""),
            "overview": (movie.get("overview") or "")[:300],
            "rating": round(movie.get("vote_average", 0), 1),
            "year": (movie.get("release_date") or "")[:4],
            "poster_url": poster,
            "_tmdb": True,
        }
    except Exception:
        return None


# ── 串流平台（TMDB watch/providers）──────────────

def get_streaming(title: str) -> list:
    return get_tmdb_streaming_by_title(title)


def get_tmdb_streaming_by_title(title: str) -> list:
    if not TMDB_KEY:
        return []
    try:
        r = requests.get(
            "https://api.themoviedb.org/3/search/movie",
            params={"api_key": TMDB_KEY, "query": title, "language": "zh-TW"},
            timeout=10,
        )
        if _check_quota(r):
            return [{"_quota": True}]
        results = r.json().get("results", [])
        if not results:
            return []
        movie_id = results[0]["id"]
        r2 = requests.get(
            f"https://api.themoviedb.org/3/movie/{movie_id}/watch/providers",
            params={"api_key": TMDB_KEY},
            timeout=10,
        )
        if _check_quota(r2):
            return [{"_quota": True}]
        tw = r2.json().get("results", {}).get("TW", {})
        providers = []
        seen = set()
        for ptype in ["flatrate", "free", "rent", "buy"]:
            for p in tw.get(ptype, []):
                name = p.get("provider_name", "")
                if name and name not in seen:
                    providers.append({"service": name, "type": ptype})
                    seen.add(name)
        return providers[:8]
    except Exception:
        return []


# ── BMI 計算（本地計算）──────────────────────────

def calc_bmi(height_cm: float, weight_kg: float) -> dict:
    bmi = round(weight_kg / (height_cm / 100) ** 2, 1)
    if bmi < 18.5:
        cat = "體重過輕 😟"
    elif bmi < 24:
        cat = "正常範圍 😊"
    elif bmi < 27:
        cat = "過重 😐"
    elif bmi < 30:
        cat = "輕度肥胖 😬"
    else:
        cat = "中重度肥胖 ⚠️"
    return {"bmi": bmi, "category": cat}


# ── 食物熱量（API-Ninjas 直連）──────────────────

def get_nutrition(query: str) -> list[dict]:
    if not APININJAS_KEY:
        return []
    try:
        r = requests.get("https://api.api-ninjas.com/v1/nutrition",
                         headers=_apininjas_headers(), params={"query": query}, timeout=10)
        if _check_quota(r):
            return [{"_quota": True}]
        return r.json().get("items", [])
    except Exception:
        return []


# ── 食譜搜尋（TheMealDB，免費無需 key）──────────

def search_recipes_by_ingredients(ingredients: str) -> list[dict]:
    try:
        first = ingredients.split(",")[0].split("、")[0].strip()
        r = requests.get(
            "https://www.themealdb.com/api/json/v1/1/filter.php",
            params={"i": first},
            timeout=10,
        )
        meals = r.json().get("meals") or []
        return [{"title": m["strMeal"]} for m in meals[:5]]
    except Exception:
        return []


# ── Chuck Norris 笑話（免費無需 key）────────────

def get_chuck_norris() -> str:
    try:
        r = requests.get("https://api.chucknorris.io/jokes/random", timeout=8)
        return r.json().get("value", "")
    except Exception:
        return ""


# ── 激勵名言（API-Ninjas 優先，fallback type.fit）

def get_motivation_quote() -> dict | None:
    try:
        if APININJAS_KEY:
            r = requests.get("https://api.api-ninjas.com/v1/quotes",
                             headers=_apininjas_headers(), timeout=8)
            if _check_quota(r):
                return {"_quota": True}
            items = r.json()
            if items:
                return {"text": items[0].get("quote", ""), "author": items[0].get("author", "Unknown")}
        r = requests.get("https://type.fit/api/quotes", timeout=8)
        quotes = r.json()
        if quotes:
            q = random.choice(quotes)
            return {"text": q.get("text", ""), "author": q.get("author") or "Unknown"}
        return None
    except Exception:
        return None


# ── 電影台詞（Gemini 負責）──────────────────────

def get_movie_quote() -> dict | None:
    return None  # webhook.py 有 Gemini fallback


# ── 天文冷知識（API-Ninjas 直連）────────────────

def get_astronomy_fact() -> str:
    if not APININJAS_KEY:
        return ""
    try:
        r = requests.get("https://api.api-ninjas.com/v1/facts",
                         headers=_apininjas_headers(), params={"category": "science"}, timeout=10)
        if _check_quota(r):
            return QUOTA_MSG
        items = r.json()
        return items[0].get("fact", "") if items else ""
    except Exception:
        return ""


# ── 消耗熱量（API-Ninjas 直連）──────────────────

def get_calories_burned(activity: str, weight_kg: float = 60, duration_min: int = 30) -> list[dict]:
    if not APININJAS_KEY:
        return []
    params = {"activity": activity, "weight": str(weight_kg), "duration": str(duration_min)}
    try:
        r = requests.get("https://api.api-ninjas.com/v1/caloriesburned",
                         headers=_apininjas_headers(), params=params, timeout=10)
        if _check_quota(r):
            return [{"_quota": True}]
        return r.json()
    except Exception:
        return []


# ── 日文字典（Jisho，免費無需 key）──────────────

JLPT_N5_KANJI = [
    "日", "月", "火", "水", "木", "金", "土", "山", "川", "田",
    "人", "口", "目", "耳", "手", "足", "上", "下", "中", "大",
    "小", "一", "二", "三", "四", "五", "六", "七", "八", "九",
    "十", "百", "千", "年", "時", "間", "学", "校", "先", "生",
    "友", "家", "会", "社", "車", "電", "駅", "道", "食", "飲",
    "見", "聞", "話", "読", "書", "来", "行", "国", "語", "本",
    "花", "犬", "猫", "魚", "鳥", "空", "海", "雨", "雪", "風",
]

JLPT_N5_WORDS = [
    "食べる", "飲む", "行く", "来る", "見る", "聞く", "話す", "読む", "書く", "買う",
    "起きる", "寝る", "食べ物", "飲み物", "学校", "電車", "友達", "家族", "先生",
    "毎日", "今日", "明日", "昨日", "今年", "来年", "去年", "時間", "場所",
    "日本語", "英語", "中国語", "言葉", "勉強", "仕事", "休み", "旅行",
    "電話", "新聞", "雑誌", "料理", "音楽", "映画", "写真", "天気",
]


def get_jisho(word: str) -> dict | None:
    try:
        r = requests.get(
            "https://jisho.org/api/v1/search/words",
            params={"keyword": word},
            timeout=10,
        )
        data = r.json().get("data", [])
        if not data:
            return None
        entry = data[0]
        readings = entry.get("japanese", [{}])
        senses = entry.get("senses", [{}])
        meanings_en = []
        for s in senses[:3]:
            meanings_en.extend(s.get("english_definitions", [])[:2])
        return {
            "word": readings[0].get("word") or readings[0].get("reading", word),
            "reading": readings[0].get("reading", ""),
            "meanings_en": meanings_en[:4],
            "jlpt": entry.get("jlpt", []),
            "common": entry.get("is_common", False),
        }
    except Exception:
        return None


def get_kanji_info(char: str) -> dict | None:
    try:
        r = requests.get(f"https://kanjiapi.dev/v1/kanji/{char}", timeout=8)
        if r.status_code != 200:
            return None
        d = r.json()
        return {
            "kanji": d.get("kanji", ""),
            "meanings": d.get("meanings", [])[:4],
            "kun_readings": d.get("kun_readings", [])[:3],
            "on_readings": d.get("on_readings", [])[:3],
            "jlpt": d.get("jlpt"),
            "stroke_count": d.get("stroke_count"),
        }
    except Exception:
        return None


def get_random_jlpt_word() -> dict | None:
    word = random.choice(JLPT_N5_WORDS)
    return get_jisho(word)


# ── 西班牙文字典（Free Dictionary API，免費無需 key）

def get_spanish_dict(word: str) -> dict | None:
    try:
        r = requests.get(
            f"https://api.dictionaryapi.dev/api/v2/entries/es/{word}",
            timeout=8,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        if not data or isinstance(data, dict):
            return None
        entry = data[0]
        meanings = entry.get("meanings", [])
        definitions = []
        for m in meanings[:2]:
            for d in m.get("definitions", [])[:2]:
                df = d.get("definition", "")
                if df:
                    definitions.append(df)
        return {
            "word": entry.get("word", word),
            "phonetic": entry.get("phonetic", ""),
            "definitions": definitions[:3],
        }
    except Exception:
        return None


# ── TheMealDB（免費無需 key）──────────────────────

def get_meal_random() -> dict | None:
    try:
        r = requests.get(
            "https://www.themealdb.com/api/json/v1/1/random.php",
            timeout=10,
        )
        meals = r.json().get("meals", [])
        if not meals:
            return None
        m = meals[0]
        ingredients = []
        for i in range(1, 21):
            ing = (m.get(f"strIngredient{i}") or "").strip()
            meas = (m.get(f"strMeasure{i}") or "").strip()
            if ing:
                ingredients.append(f"{ing} {meas}".strip())
        return {
            "name": m.get("strMeal", ""),
            "category": m.get("strCategory", ""),
            "area": m.get("strArea", ""),
            "instructions": (m.get("strInstructions") or "")[:400],
            "ingredients": ingredients[:8],
            "youtube": m.get("strYoutube", ""),
        }
    except Exception:
        return None


# ── Open Trivia DB（免費無需 key）────────────────

def get_open_trivia() -> dict | None:
    try:
        r = requests.get(
            "https://opentdb.com/api.php",
            params={"amount": 1, "type": "multiple"},
            timeout=10,
        )
        results = r.json().get("results", [])
        if not results:
            return None
        q = results[0]
        return {
            "question": _html.unescape(q.get("question", "")),
            "answer": _html.unescape(q.get("correct_answer", "")),
            "category": q.get("category", ""),
        }
    except Exception:
        return None


# ── NumbersAPI（免費無需 key）────────────────────

def get_number_fact() -> str:
    try:
        r = requests.get(
            "http://numbersapi.com/random/trivia",
            params={"json": "true"},
            timeout=8,
        )
        return r.json().get("text", "")
    except Exception:
        return ""


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
    except Exception:
        pass

    # 2. Gemini fallback
    try:
        key = _gemini_key()
        if not key:
            return text
        lang_name = _LANG_NAME.get(target_lang, target_lang)
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={key}",
            json={"contents": [{"parts": [{"text": f"把以下文字翻譯成{lang_name}，只給翻譯結果，不要解釋：\n\n{text}"}]}]},
            timeout=15,
        )
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        return f"翻譯失敗：{e}"


# ── NASA APOD（每日天文圖片）──────────────────────

def get_nasa_apod() -> dict | None:
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

_EDGE_TTS_VOICE = {
    "zh-TW": "zh-TW-HsiaoChenNeural",
    "zh-CN": "zh-CN-XiaoxiaoNeural",
    "en": "en-US-JennyNeural",
    "ja": "ja-JP-NanamiNeural",
    "ko": "ko-KR-SunHiNeural",
}

def text_to_speech(text: str, lang: str = "zh-TW") -> tuple[bytes, str] | None:
    try:
        import asyncio
        import edge_tts

        voice = _EDGE_TTS_VOICE.get(lang, "zh-TW-HsiaoChenNeural")

        async def _synth():
            communicate = edge_tts.Communicate(text[:500], voice)
            buf = io.BytesIO()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    buf.write(chunk["data"])
            return buf.getvalue()

        audio_bytes = asyncio.run(_synth())
        if audio_bytes and len(audio_bytes) > 100:
            return audio_bytes, "audio/mpeg"
        return None
    except Exception:
        return None


# ── 智慧翻譯（只翻英文，其他直接回傳）──────────

def smart_translate(text: str, target: str = "zh-TW") -> str:
    if not text or not text.strip():
        return text
    if any(ord(c) > 127 for c in text[:30]):
        return text
    return translate_text(text, target)


# ── 笑話輪班（API-Ninjas → JokeAPI.dev → Chuck Norris）

def _get_jokeapi_dev() -> str | None:
    try:
        r = requests.get(
            "https://v2.jokeapi.dev/joke/Any",
            params={"safe-mode": "", "blacklistFlags": "nsfw,racist,sexist,explicit"},
            timeout=8,
        )
        d = r.json()
        if d.get("type") == "single":
            return d.get("joke", "")
        return f"{d.get('setup', '')}\n{d.get('delivery', '')}"
    except Exception:
        return None

def get_joke_round_robin() -> str:
    result = _fallback_call(
        lambda: get_joke(),
        _get_jokeapi_dev,
        lambda: get_chuck_norris(),
    )
    return result or "今天笑話庫休息，請自行搞笑 😅"


# ── 星座輪班（Aztro → Gemini，快取 6 小時）──────

def _get_horoscope_gemini(sign_zh: str) -> dict | None:
    sign_zh = sign_zh.replace("座", "").strip()
    text = call_gemini(
        f"請用繁體中文給出今日{sign_zh}座的星座運勢，包含：運勢描述（2句）、幸運色、幸運數字、配對星座。"
        f"回覆格式：描述|幸運色|幸運數字|配對"
    )
    if not text:
        return None
    parts = text.split("|")
    return {
        "sign": sign_zh + "座",
        "description": parts[0].strip() if len(parts) > 0 else text,
        "color": parts[1].strip() if len(parts) > 1 else "—",
        "lucky_number": parts[2].strip() if len(parts) > 2 else "—",
        "compatibility": parts[3].strip() if len(parts) > 3 else "—",
        "mood": "—",
    }

def get_horoscope_round_robin(sign: str) -> dict | None:
    return _fallback_call(
        lambda: get_horoscope(sign),
        lambda: _get_horoscope_gemini(sign),
    )


# ── 星座配對（Gemini）────────────────────────────

def get_starmatch(sign1: str, sign2: str) -> dict | None:
    text = call_gemini(
        f"請分析{sign1}座和{sign2}座的配對，用繁體中文回覆。"
        f"格式：相容度分數(0-100)|一句描述。只給這兩部分，用|分隔。"
    )
    if not text:
        return None
    parts = text.split("|")
    return {
        "sign1": sign1,
        "sign2": sign2,
        "compatibility": parts[0].strip() if parts else "?",
        "description": parts[1].strip() if len(parts) > 1 else text,
    }


# ── 新聞（Google News RSS，免費無需 key，快取 1 小時）

def get_news_round_robin() -> list[dict]:
    def _fetch():
        try:
            import xml.etree.ElementTree as ET
            r = requests.get(
                "https://news.google.com/rss?hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            root = ET.fromstring(r.content)
            items = root.findall(".//item")[:5]
            news = []
            for item in items:
                title = item.findtext("title", "")
                if " - " in title:
                    title = title.rsplit(" - ", 1)[0]
                news.append({"title": title, "url": item.findtext("link", ""), "desc": ""})
            return news or None
        except Exception:
            return None
    return _cached("news", 3600, _fetch) or []


# ── TTS 音檔暫存管理 ─────────────────────────────

_tts_cache: dict[str, tuple[bytes, str, float]] = {}

def save_tts_audio(audio_bytes: bytes, mime_type: str = "audio/mpeg") -> str:
    fname = f"tts_{int(time.time()*1000)}.m4a"
    _tts_cache[fname] = (audio_bytes, mime_type, time.time())
    if len(_tts_cache) > 50:
        oldest = sorted(_tts_cache.items(), key=lambda x: x[1][2])[0][0]
        _tts_cache.pop(oldest, None)
    return fname

def get_tts_audio(filename: str) -> tuple[bytes, str] | None:
    entry = _tts_cache.get(filename)
    if entry:
        return entry[0], entry[1]
    return None
