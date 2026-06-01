"""Entertainment Api for line-family-bot."""

import requests
import os
from datetime import datetime, timedelta
import random
import logging
logger = logging.getLogger(__name__)

from api_helpers import (
_retry_http, _cached, _check_quota, _apininjas_headers, call_gemini, call_groq, QUOTA_MSG, TMDB_KEY, NASA_KEY, PEXELS_KEY, NEWSAPI_KEY, ABSTRACT_KEY
)



SIGN_MAP = {
    "牡羊": "aries", "金牛": "taurus", "雙子": "gemini", "巨蟹": "cancer",
    "獅子": "leo", "處女": "virgo", "天秤": "libra", "天蠍": "scorpio",
    "射手": "sagittarius", "摩羯": "capricorn", "水瓶": "aquarius", "雙魚": "pisces",
}

def get_advice() -> str:
    try:
        r = requests.get("https://api.adviceslip.com/advice", timeout=5)
        return r.json()["slip"]["advice"]
    except Exception:
        return ""

def get_fun_fact() -> str:
    try:
        r = requests.get(
            "https://uselessfacts.jsph.pl/api/v2/facts/random",
            params={"language": "en"}, timeout=8,
        )
        return r.json().get("text", "")
    except Exception:
        return ""

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

def get_random_activity() -> dict | None:
    try:
        r = requests.get("https://bored-api.appbrewery.com/random", timeout=10)
        d = r.json()
        return {"activity": d.get("activity", ""), "participants": d.get("participants", 1), "type": d.get("type", "")}
    except Exception:
        return None

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
    except Exception as _exc:
        logger.warning("API error: %s", _exc)
    return None

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

def generate_image(prompt: str) -> str | None:
    try:
        encoded = requests.utils.quote(prompt)
        return f"https://image.pollinations.ai/prompt/{encoded}?width=512&height=512&nologo=true&seed={random.randint(1,9999)}"
    except Exception:
        return None

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

def get_chuck_norris() -> str:
    try:
        r = requests.get("https://api.chucknorris.io/jokes/random", timeout=8)
        return r.json().get("value", "")
    except Exception:
        return ""

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

def get_movie_quote() -> dict | None:
    return None  # webhook.py 有 Gemini fallback

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
    return result or call_groq("說一個適合全家的台灣笑話，繁體中文") or "今天笑話庫休息，請自行搞笑 😅"

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
    result = get_horoscope(sign)
    if result:
        return result
    return _get_horoscope_gemini(sign)

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

def search_photo(query: str) -> str | None:
    if not PEXELS_KEY:
        return None
    try:
        r = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": PEXELS_KEY},
            params={"query": query, "per_page": 5, "orientation": "landscape"},
            timeout=10,
        )
        photos = r.json().get("photos", [])
        if photos:
            photo = random.choice(photos[:5])
            return photo["src"].get("large2x") or photo["src"].get("large")
    except Exception as e:
        logger.warning("[pexels] %s", e)
    return None


def get_curated_photo() -> str | None:
    if not PEXELS_KEY:
        return None
    def _fetch():
        try:
            r = requests.get(
                "https://api.pexels.com/v1/curated",
                headers={"Authorization": PEXELS_KEY},
                params={"per_page": 10},
                timeout=10,
            )
            photos = r.json().get("photos", [])
            if photos:
                photo = random.choice(photos)
                return photo["src"].get("large2x") or photo["src"].get("large")
        except Exception as e:
            logger.warning("[pexels curated] %s", e)
        return None
    return _cached("pexels_curated", 3600, _fetch)

def _get_news_newsapi() -> list[dict] | None:
    if not NEWSAPI_KEY:
        return None
    try:
        r = requests.get(
            "https://newsapi.org/v2/top-headlines",
            params={"country": "tw", "pageSize": 5, "apiKey": NEWSAPI_KEY},
            timeout=10,
        )
        articles = r.json().get("articles", [])
        if not articles:
            return None
        return [
            {"title": a.get("title", ""), "url": a.get("url", ""), "desc": a.get("description", "")}
            for a in articles if a.get("title")
        ]
    except Exception as e:
        logger.warning("[newsapi] %s", e)
    return None


def _get_news_rss() -> list[dict] | None:
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


def get_news_round_robin() -> list[dict]:
    def _fetch():
        return _get_news_newsapi() or _get_news_rss()
    return _cached("news", 3600, _fetch) or []

def get_holidays(year: int = None, month: int = None, day: int = None, country: str = "TW") -> list[dict]:
    if not ABSTRACT_KEY:
        return []
    now = datetime.now()
    y = year or now.year
    m = month or now.month
    d = day or now.day
    cache_key = f"holidays_{country}_{y}_{m}_{d}"
    def _fetch():
        try:
            r = requests.get(
                "https://holidays.abstractapi.com/v1/",
                params={"api_key": ABSTRACT_KEY, "country": country, "year": y, "month": m, "day": d},
                timeout=10,
            )
            data = r.json()
            if isinstance(data, list):
                return data or []
            return []
        except Exception as e:
            logger.warning("[holidays] %s", e)
            return []
    return _cached(cache_key, 86400, _fetch) or []

def get_wikipedia(query: str) -> dict | None:
    for lang in ("zh", "en"):
        try:
            r = requests.get(
                f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{requests.utils.quote(query)}",
                headers={"User-Agent": "line-family-bot/1.0"},
                timeout=10,
            )
            if r.status_code == 200:
                d = r.json()
                return {
                    "title": d.get("title", ""),
                    "extract": d.get("extract", ""),
                    "url": d.get("content_urls", {}).get("mobile", {}).get("page", ""),
                }
        except Exception as e:
            logger.warning("[wiki] %s", e)
    return None

def make_qr_url(data: str, size: int = 300) -> str:
    return f"https://api.qrserver.com/v1/create-qr-code/?size={size}x{size}&data={requests.utils.quote(data)}"

def get_cat_image() -> str | None:
    try:
        r = requests.get("https://api.thecatapi.com/v1/images/search", timeout=8)
        items = r.json()
        if items:
            return items[0].get("url")
    except Exception as e:
        logger.warning("[cat] %s", e)
    return None

def get_dog_image() -> str | None:
    try:
        r = requests.get("https://dog.ceo/api/breeds/image/random", timeout=8)
        return r.json().get("message")
    except Exception as e:
        logger.warning("[dog] %s", e)
    return None
