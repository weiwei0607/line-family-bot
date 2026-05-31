"""
API 工具集：天氣、AQI、星座、笑話、問答、飲料、運動、動漫、圖片生成、
匯率、金價、電影、串流平台、BMI、食物熱量、隨機活動、日文、西班牙文
"""

import os
import html as _html
import random
import requests

LAT = float(os.environ.get("LOCATION_LAT", "25.04"))
LON = float(os.environ.get("LOCATION_LON", "121.53"))
WEATHER_CITY = os.environ.get("WEATHER_CITY", "Taipei")
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "")
APININJAS_KEY = os.environ.get("APININJAS_KEY", "")
NASA_KEY = os.environ.get("NASA_API_KEY", "")

QUOTA_MSG = "❌ 今日 API 額度用完了，明天再試試！"

def _check_quota(r) -> bool:
    return r.status_code == 429

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


def _rapidapi_headers(host: str) -> dict:
    return {"X-RapidAPI-Key": RAPIDAPI_KEY, "X-RapidAPI-Host": host}


def _apininjas_headers() -> dict:
    return {"X-Api-Key": APININJAS_KEY}


# ── 天氣（Open-Meteo，無需 key）──────────────────

def get_weather() -> dict:
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


def get_aqi() -> dict:
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


def format_weather_block() -> str:
    # 優先使用 WeatherAPI，fallback 到 Open-Meteo
    if RAPIDAPI_KEY:
        w = get_weather_api()
        if "error" not in w:
            lines = [
                f"{w['condition']}　{w['temp_c']}°C（體感 {w['feelslike_c']}°）",
                f"濕度 {w['humidity']}%　風速 {w['wind_kph']} km/h　UV {w['uv']}",
            ]
            a = get_aqi()
            if "error" not in a:
                lines.append(f"空氣品質 AQI {a['aqi']}（{a['level']}）")
            return "\n".join(lines)
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


# ── WeatherAPI.com（RapidAPI）────────────────────

def get_weather_api() -> dict:
    try:
        r = requests.get(
            "https://weatherapi-com.p.rapidapi.com/current.json",
            headers=_rapidapi_headers("weatherapi-com.p.rapidapi.com"),
            params={"q": WEATHER_CITY},
            timeout=10,
        )
        cur = r.json()["current"]
        return {
            "condition": cur["condition"]["text"],
            "temp_c": round(cur["temp_c"]),
            "feelslike_c": round(cur["feelslike_c"]),
            "humidity": cur["humidity"],
            "wind_kph": round(cur["wind_kph"]),
            "uv": cur["uv"],
        }
    except Exception as e:
        return {"error": str(e)}


# ── 人生建議（免費無需 key）──────────────────────

def get_advice() -> str:
    try:
        r = requests.get("https://api.adviceslip.com/advice", timeout=5)
        return r.json()["slip"]["advice"]
    except Exception:
        return ""


# ── 冷知識（免費無需 key）────────────────────────

def get_fun_fact() -> str:
    try:
        r = requests.get(
            "https://uselessfacts.jsph.pl/api/v2/facts/random",
            params={"language": "en"}, timeout=8,
        )
        return r.json().get("text", "")
    except Exception:
        return ""


# ── 星座運勢（aztro，免費無需 key）──────────────

def get_horoscope(sign_zh: str) -> dict | None:
    sign_zh = sign_zh.replace("座", "").strip()
    sign_en = SIGN_MAP.get(sign_zh)
    if not sign_en:
        return None
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


# ── 笑話（API-Ninjas / JokeAPI v2）──────────────

def get_joke() -> str:
    try:
        if APININJAS_KEY:
            r = requests.get("https://api.api-ninjas.com/v1/jokes",
                             headers=_apininjas_headers(), timeout=10)
            if _check_quota(r): return QUOTA_MSG
            items = r.json()
            return items[0].get("joke", "") if items else ""
        if RAPIDAPI_KEY:
            r = requests.get("https://jokeapi-v2.p.rapidapi.com/joke/Any",
                             headers=_rapidapi_headers("jokeapi-v2.p.rapidapi.com"),
                             params={"safe-mode": "", "format": "json"}, timeout=10)
            if _check_quota(r): return QUOTA_MSG
            d = r.json()
            if d.get("type") == "single":
                return d.get("joke", "")
            return f"{d.get('setup', '')}\n\n{d.get('delivery', '')}"
        return ""
    except Exception:
        return ""


# ── 問答題（Trivia by API-Ninjas）───────────────

def get_trivia() -> dict | None:
    try:
        if APININJAS_KEY:
            r = requests.get("https://api.api-ninjas.com/v1/trivia",
                             headers=_apininjas_headers(), timeout=10)
        elif RAPIDAPI_KEY:
            r = requests.get("https://trivia-by-api-ninjas.p.rapidapi.com/v1/trivia",
                             headers=_rapidapi_headers("trivia-by-api-ninjas.p.rapidapi.com"), timeout=10)
        else:
            return None
        if _check_quota(r): return {"_quota": True}
        items = r.json()
        return {"question": items[0].get("question", ""), "answer": items[0].get("answer", "")} if items else None
    except Exception:
        return None


# ── 飲料食譜（Cocktail by API-Ninjas）───────────

def get_cocktail(name: str = "") -> dict | None:
    params = {"name": name if name else random.choice(["lemonade", "tea", "smoothie", "juice"])}
    try:
        if APININJAS_KEY:
            r = requests.get("https://api.api-ninjas.com/v1/cocktail",
                             headers=_apininjas_headers(), params=params, timeout=10)
        elif RAPIDAPI_KEY:
            r = requests.get("https://cocktail-by-api-ninjas.p.rapidapi.com/v1/cocktail",
                             headers=_rapidapi_headers("cocktail-by-api-ninjas.p.rapidapi.com"),
                             params=params, timeout=10)
        else:
            return None
        if _check_quota(r): return {"_quota": True}
        items = r.json()
        return items[0] if items else None
    except Exception:
        return None


# ── 隨機活動（Random Activity Generator）────────

def get_random_activity() -> dict | None:
    if not RAPIDAPI_KEY:
        return None
    try:
        r = requests.get(
            "https://random-activity-generator.p.rapidapi.com/activity",
            headers=_rapidapi_headers("random-activity-generator.p.rapidapi.com"),
            timeout=10,
        )
        if _check_quota(r): return {"_quota": True}
        return r.json()
    except Exception:
        return None


# ── 運動建議（ExerciseDB）────────────────────────

def get_exercise() -> dict | None:
    if not RAPIDAPI_KEY:
        return None
    try:
        offset = random.randint(0, 800)
        r = requests.get(
            "https://exercisedb.p.rapidapi.com/exercises",
            headers=_rapidapi_headers("exercisedb.p.rapidapi.com"),
            params={"limit": "1", "offset": str(offset)},
            timeout=10,
        )
        if _check_quota(r): return {"_quota": True}
        items = r.json()
        return items[0] if items else None
    except Exception:
        return None


# ── 動漫名言（Anime Quotes）──────────────────────

def get_anime_quote() -> dict | None:
    if not RAPIDAPI_KEY:
        return None
    try:
        r = requests.get(
            "https://anime-quotes-7.p.rapidapi.com/api/v1/quote",
            headers=_rapidapi_headers("anime-quotes-7.p.rapidapi.com"),
            timeout=10,
        )
        if _check_quota(r): return {"_quota": True}
        return r.json()
    except Exception:
        return None


# ── AI 圖片生成（Flux Free）──────────────────────

def generate_image(prompt: str) -> str | None:
    if not RAPIDAPI_KEY:
        return None
    try:
        r = requests.post(
            "https://ai-text-to-image-generator-flux-free-api.p.rapidapi.com/aaaaaaa",
            headers={
                **_rapidapi_headers("ai-text-to-image-generator-flux-free-api.p.rapidapi.com"),
                "Content-Type": "application/json",
            },
            json={"prompt": prompt, "width": 512, "height": 512},
            timeout=30,
        )
        if _check_quota(r): return QUOTA_MSG
        d = r.json()
        return (d.get("url") or d.get("imageUrl") or d.get("image_url")
                or d.get("output") or (d.get("images") or [None])[0])
    except Exception:
        return None


# ── 匯率（Currency Conversion）──────────────────

def get_currency(from_curr: str, to_curr: str = "TWD") -> dict | None:
    if not RAPIDAPI_KEY:
        return None
    from_curr = CURRENCY_MAP.get(from_curr, from_curr.upper())
    to_curr = CURRENCY_MAP.get(to_curr, to_curr.upper())
    try:
        r = requests.get(
            "https://currency-conversion-and-exchange-rates.p.rapidapi.com/convert",
            headers=_rapidapi_headers("currency-conversion-and-exchange-rates.p.rapidapi.com"),
            params={"from": from_curr, "to": to_curr, "amount": "1"},
            timeout=10,
        )
        if _check_quota(r): return {"_quota": True}
        d = r.json()
        return {"from": from_curr, "to": to_curr, "rate": round(d.get("result", 0), 4)}
    except Exception:
        return None


# ── 金價（Gold Price Live）───────────────────────

def get_gold_price() -> dict | None:
    if not RAPIDAPI_KEY:
        return None
    try:
        r = requests.get(
            "https://gold-price-live.p.rapidapi.com/get_metal_prices",
            headers=_rapidapi_headers("gold-price-live.p.rapidapi.com"),
            timeout=10,
        )
        if _check_quota(r): return {"_quota": True}
        d = r.json()
        metals = d.get("metals", d)
        gold = metals.get("XAU") or metals.get("gold") or metals.get("GOLD")
        silver = metals.get("XAG") or metals.get("silver") or metals.get("SILVER")
        return {"gold_usd": gold, "silver_usd": silver}
    except Exception:
        return None


# ── 電影（IMDb Top 100）──────────────────────────

def get_movie(title: str = "") -> dict | None:
    if not RAPIDAPI_KEY:
        return None
    try:
        r = requests.get(
            "https://imdb-top-100-movies.p.rapidapi.com/",
            headers=_rapidapi_headers("imdb-top-100-movies.p.rapidapi.com"),
            timeout=10,
        )
        if _check_quota(r): return {"_quota": True}
        movies = r.json()
        if not movies:
            return None
        if title:
            matched = next((m for m in movies if title.lower() in m.get("title", "").lower()), None)
            return matched or random.choice(movies)
        return random.choice(movies)
    except Exception:
        return None


# ── 串流平台（Streaming Availability）───────────

def get_streaming(title: str) -> list:
    if not RAPIDAPI_KEY:
        return []
    try:
        r = requests.get(
            "https://streaming-availability.p.rapidapi.com/shows/search/title",
            headers=_rapidapi_headers("streaming-availability.p.rapidapi.com"),
            params={"title": title, "country": "tw", "show_type": "movie"},
            timeout=10,
        )
        if _check_quota(r): return [{"_quota": True}]
        results = r.json()
        if isinstance(results, list) and results:
            opts = results[0].get("streamingOptions", {}).get("tw", [])
            return [{"service": o.get("service", {}).get("name", ""), "link": o.get("link", "")} for o in opts[:5]]
        return []
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


# ── 食物熱量（CalorieNinjas / API-Ninjas）────────

def get_nutrition(query: str) -> list[dict]:
    try:
        if APININJAS_KEY:
            r = requests.get("https://api.api-ninjas.com/v1/nutrition",
                             headers=_apininjas_headers(), params={"query": query}, timeout=10)
        elif RAPIDAPI_KEY:
            r = requests.get("https://calorieninjas.p.rapidapi.com/v1/nutrition",
                             headers=_rapidapi_headers("calorieninjas.p.rapidapi.com"),
                             params={"query": query}, timeout=10)
        else:
            return []
        if _check_quota(r): return [{"_quota": True}]
        return r.json().get("items", [])
    except Exception:
        return []


# ── 食譜搜尋（Spoonacular via RapidAPI）──────────

def search_recipes_by_ingredients(ingredients: str) -> list[dict]:
    if not RAPIDAPI_KEY:
        return []
    try:
        r = requests.get(
            "https://spoonacular-recipe-food-nutrition-v1.p.rapidapi.com/recipes/findByIngredients",
            headers=_rapidapi_headers("spoonacular-recipe-food-nutrition-v1.p.rapidapi.com"),
            params={"ingredients": ingredients, "number": 3, "ranking": 1},
            timeout=10,
        )
        return r.json()
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
            if _check_quota(r): return {"_quota": True}
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


# ── 電影台詞（Movie Quotes by API-Ninjas）────────

def get_movie_quote() -> dict | None:
    if not RAPIDAPI_KEY:
        return None
    try:
        r = requests.get(
            "https://movie-quote-api.p.rapidapi.com/v1/quote/",
            headers=_rapidapi_headers("movie-quote-api.p.rapidapi.com"),
            timeout=10,
        )
        if _check_quota(r): return {"_quota": True}
        d = r.json()
        return {"quote": d.get("quote", ""), "movie": d.get("movie", ""), "character": d.get("character", "")}
    except Exception:
        return None


# ── 天文冷知識（Facts by API-Ninjas）────────────

def get_astronomy_fact() -> str:
    try:
        if APININJAS_KEY:
            r = requests.get("https://api.api-ninjas.com/v1/facts",
                             headers=_apininjas_headers(), params={"category": "science"}, timeout=10)
        elif RAPIDAPI_KEY:
            r = requests.get("https://facts-by-api-ninjas.p.rapidapi.com/v1/facts",
                             headers=_rapidapi_headers("facts-by-api-ninjas.p.rapidapi.com"),
                             params={"category": "science"}, timeout=10)
        else:
            return ""
        if _check_quota(r): return QUOTA_MSG
        items = r.json()
        return items[0].get("fact", "") if items else ""
    except Exception:
        return ""


# ── 消耗熱量（Calories Burned by API-Ninjas）─────

def get_calories_burned(activity: str, weight_kg: float = 60, duration_min: int = 30) -> list[dict]:
    params = {"activity": activity, "weight": str(weight_kg), "duration": str(duration_min)}
    try:
        if APININJAS_KEY:
            r = requests.get("https://api.api-ninjas.com/v1/caloriesburned",
                             headers=_apininjas_headers(), params=params, timeout=10)
        elif RAPIDAPI_KEY:
            r = requests.get("https://calories-burned-by-api-ninjas.p.rapidapi.com/v1/caloriesburned",
                             headers=_rapidapi_headers("calories-burned-by-api-ninjas.p.rapidapi.com"),
                             params=params, timeout=10)
        else:
            return []
        if _check_quota(r): return [{"_quota": True}]
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


# ── 翻譯（使用 Gemini 免費高品質翻譯）─────────────

def translate_text(text: str, target_lang: str = "zh-TW", source_lang: str = "auto") -> str:
    """翻譯文字。target_lang: zh-TW, en, ja, ko, es, fr, de 等"""
    try:
        gemini_key = os.environ.get("GEMINI_API_KEY", "")
        if not gemini_key:
            return "（需要設定 GEMINI_API_KEY）"
        lang_name = {
            "zh-TW": "繁體中文", "zh-CN": "簡體中文", "en": "英文",
            "ja": "日文", "ko": "韓文", "es": "西班牙文", "fr": "法文",
            "de": "德文", "th": "泰文", "vi": "越南文", "id": "印尼文",
        }.get(target_lang, target_lang)
        prompt = f"把以下文字翻譯成{lang_name}，只給翻譯結果，不要解釋：\n\n{text}"
        url = (
            "https://generativelanguage.googleapis.com/v1beta/"
            f"models/gemini-2.5-flash:generateContent?key={gemini_key}"
        )
        resp = requests.post(
            url,
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=15,
        )
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        return f"翻譯失敗：{e}"


# ── 翻譯（MyMemory，免費無需 key）────────────────

def translate_text(text: str, target: str = "zh-TW") -> str:
    if not text:
        return text
    lang_map = {"zh-TW": "zh-TW", "zh": "zh-TW", "ja": "ja-JP", "es": "es-ES", "en": "en-US"}
    tgt = lang_map.get(target, target)
    try:
        r = requests.get(
            "https://api.mymemory.translated.net/get",
            params={"q": text[:300], "langpair": f"en|{tgt}"},
            timeout=8,
        )
        result = r.json().get("responseData", {}).get("translatedText", "")
        return result if result and result != "NO QUERY SPECIFIED" else text
    except Exception:
        return text


# ── NASA APOD（每日天文圖片）──────────────────────

def get_nasa_apod() -> dict | None:
    if not NASA_KEY:
        return None
    try:
        r = requests.get(
            "https://api.nasa.gov/planetary/apod",
            params={"api_key": NASA_KEY},
            timeout=12,
        )
        if _check_quota(r): return {"_quota": True}
        d = r.json()
        return {
            "title": d.get("title", ""),
            "date": d.get("date", ""),
            "explanation": (d.get("explanation") or "")[:500],
            "url": d.get("url", ""),
            "hdurl": d.get("hdurl") or d.get("url", ""),
            "media_type": d.get("media_type", "image"),
        }
    except Exception:
        return None


# ── 電影（IMDB，fallback）────────────────────────

def get_movie_by_genre(genre: str) -> dict | None:
    return None
