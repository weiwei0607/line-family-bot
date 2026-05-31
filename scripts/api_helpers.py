"""
API 小工具：天氣、空氣品質、人生建議、星座、食譜、營養、冷知識
"""

import os
import requests

LAT = float(os.environ.get("LOCATION_LAT", "25.04"))
LON = float(os.environ.get("LOCATION_LON", "121.53"))
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "")

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


# ── 天氣 ──────────────────────────────────────

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
        cur = d["current"]
        day = d["daily"]
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
        if aqi <= 50:
            level = "良好 😊"
        elif aqi <= 100:
            level = "普通 😐"
        elif aqi <= 150:
            level = "對敏感族群不健康 😷"
        else:
            level = "不健康 ⚠️"
        return {"aqi": aqi, "pm25": pm25, "level": level}
    except Exception as e:
        return {"error": str(e)}


def format_weather_block() -> str:
    w = get_weather()
    a = get_aqi()
    if "error" in w:
        return "（天氣資料取得失敗）"
    lines = [
        f"{w['condition']}　{w['temp']}°C",
        f"最高 {w['temp_max']}° / 最低 {w['temp_min']}°　降雨機率 {w['rain_prob']}%",
        f"濕度 {w['humidity']}%",
    ]
    if "error" not in a:
        lines.append(f"空氣品質 AQI {a['aqi']}（{a['level']}）PM2.5：{a['pm25']}")
    return "\n".join(lines)


# ── 人生建議 ──────────────────────────────────

def get_advice() -> str:
    try:
        r = requests.get("https://api.adviceslip.com/advice", timeout=5)
        return r.json()["slip"]["advice"]
    except Exception:
        return ""


# ── 星座運勢（aztro，免費無需 key）────────────

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
            "lucky_time": d.get("lucky_time", ""),
            "compatibility": d.get("compatibility", ""),
        }
    except Exception:
        return None


# ── 冷知識（uselessfacts，免費無需 key）────────

def get_fun_fact() -> str:
    try:
        r = requests.get(
            "https://uselessfacts.jsph.pl/api/v2/facts/random",
            params={"language": "en"},
            timeout=8,
        )
        return r.json().get("text", "")
    except Exception:
        return ""


# ── 食譜搜尋（Spoonacular via RapidAPI）────────

def search_recipes_by_ingredients(ingredients: str) -> list[dict]:
    if not RAPIDAPI_KEY:
        return []
    try:
        r = requests.get(
            "https://spoonacular-recipe-food-nutrition-v1.p.rapidapi.com/recipes/findByIngredients",
            headers={
                "X-RapidAPI-Key": RAPIDAPI_KEY,
                "X-RapidAPI-Host": "spoonacular-recipe-food-nutrition-v1.p.rapidapi.com",
            },
            params={"ingredients": ingredients, "number": 3, "ranking": 1},
            timeout=10,
        )
        return r.json()
    except Exception:
        return []


# ── 食物熱量（CalorieNinjas via RapidAPI）──────

def get_nutrition(query: str) -> list[dict]:
    if not RAPIDAPI_KEY:
        return []
    try:
        r = requests.get(
            "https://calorieninjas.p.rapidapi.com/v1/nutrition",
            headers={
                "X-RapidAPI-Key": RAPIDAPI_KEY,
                "X-RapidAPI-Host": "calorieninjas.p.rapidapi.com",
            },
            params={"query": query},
            timeout=10,
        )
        return r.json().get("items", [])
    except Exception:
        return []


# ── 電影推薦（IMDB via RapidAPI）──────────────

def get_movie_by_genre(genre: str) -> dict | None:
    if not RAPIDAPI_KEY:
        return None
    try:
        r = requests.get(
            "https://imdb8.p.rapidapi.com/title/find",
            headers={
                "X-RapidAPI-Key": RAPIDAPI_KEY,
                "X-RapidAPI-Host": "imdb8.p.rapidapi.com",
            },
            params={"q": genre},
            timeout=10,
        )
        results = r.json().get("results", [])
        movies = [x for x in results if x.get("titleType") == "movie"]
        if not movies:
            return None
        m = movies[0]
        return {
            "title": m.get("title", ""),
            "year": m.get("year", ""),
            "image": m.get("image", {}).get("url", ""),
        }
    except Exception:
        return None
