"""Travel Api for line-family-bot."""

import requests
import os
import logging
logger = logging.getLogger(__name__)

from api_helpers import (
_retry_http, call_gemini
)


def search_hotels(query: str) -> str:
    """搜尋城市飯店"""
    key = os.environ.get("RAPIDAPI_KEY", "")
    if not key:
        return ""
    try:
        r = requests.get(
            "https://hotels-com-provider.p.rapidapi.com/v2/regions",
            headers={"x-rapidapi-key": key, "x-rapidapi-host": "hotels-com-provider.p.rapidapi.com"},
            params={"query": query, "locale": "zh_TW", "domain": "TW"},
            timeout=10,
        )
        if r.status_code == 200:
            d = r.json()
            items = d.get("data", [])[:5]
            if not items:
                return f"找不到「{query}」的飯店資訊"
            lines = [f"🏨 「{query}」搜尋結果：\n"]
            for item in items:
                names = item.get("regionNames", {})
                full = names.get("fullName", "")
                short = names.get("shortName", "")
                t = item.get("type", "")
                lines.append(f"• {short or full} ({t})")
            return "\n".join(lines)
    except Exception as e:
        logger.warning("[hotels] %s", e)
    return ""

def search_airports(query: str) -> str:
    """搜尋機場"""
    key = os.environ.get("RAPIDAPI_KEY", "")
    if not key:
        return ""
    try:
        r = requests.post(
            "https://airports.p.rapidapi.com/v1/airports",
            headers={"x-rapidapi-key": key, "x-rapidapi-host": "airports.p.rapidapi.com", "Content-Type": "application/json"},
            json={"search": query},
            timeout=10,
        )
        if r.status_code == 200:
            items = r.json()[:5]
            if not items:
                return f"找不到「{query}」的機場"
            lines = [f"✈️ 「{query}」機場搜尋結果：\n"]
            for item in items:
                name = item.get("name", "")
                iata = item.get("iata", "")
                icao = item.get("icao", "")
                city = item.get("city", "")
                country = item.get("country_name", "")
                code_str = f" ({iata}/{icao})" if iata or icao else ""
                lines.append(f"• {name}{code_str} — {city}, {country}")
            return "\n".join(lines)
    except Exception as e:
        logger.warning("[airports] %s", e)
    return ""

_TZ_MAP = {
    "東京": "Asia/Tokyo", "日本": "Asia/Tokyo",
    "首爾": "Asia/Seoul", "韓國": "Asia/Seoul",
    "北京": "Asia/Shanghai", "上海": "Asia/Shanghai", "中國": "Asia/Shanghai",
    "香港": "Asia/Hong_Kong",
    "新加坡": "Asia/Singapore",
    "曼谷": "Asia/Bangkok", "泰國": "Asia/Bangkok",
    "台北": "Asia/Taipei", "台灣": "Asia/Taipei",
    "杜拜": "Asia/Dubai",
    "莫斯科": "Europe/Moscow",
    "倫敦": "Europe/London", "英國": "Europe/London",
    "巴黎": "Europe/Paris", "法國": "Europe/Paris",
    "柏林": "Europe/Berlin", "德國": "Europe/Berlin",
    "紐約": "America/New_York", "美東": "America/New_York",
    "洛杉磯": "America/Los_Angeles", "美西": "America/Los_Angeles",
    "雪梨": "Australia/Sydney", "澳洲": "Australia/Sydney",
    "奧克蘭": "Pacific/Auckland", "紐西蘭": "Pacific/Auckland",
}

def get_world_time(city: str) -> dict | None:
    tz = _TZ_MAP.get(city) or city
    try:
        r = requests.get(f"https://worldtimeapi.org/api/timezone/{tz}", timeout=8)
        if r.status_code != 200:
            return None
        d = r.json()
        dt_str = d.get("datetime", "")[:19].replace("T", " ")
        return {"city": city, "tz": tz, "datetime": dt_str}
    except Exception as e:
        logger.warning("[worldtime] %s", e)
    return None

def get_country_info(name: str) -> dict | None:
    try:
        r = requests.get(
            f"https://restcountries.com/v3.1/name/{requests.utils.quote(name)}",
            timeout=10,
        )
        if r.status_code != 200:
            return None
        c = r.json()[0]
        langs = ", ".join(c.get("languages", {}).values())
        currencies = ", ".join(
            f"{v.get('name', k)}({v.get('symbol', '')})"
            for k, v in c.get("currencies", {}).items()
        )
        return {
            "name": c.get("name", {}).get("official", name),
            "capital": ", ".join(c.get("capital", [])),
            "region": c.get("region", ""),
            "population": c.get("population", 0),
            "area": c.get("area", 0),
            "languages": langs,
            "currencies": currencies,
            "flag": c.get("flag", ""),
        }
    except Exception as e:
        logger.warning("[country] %s", e)
    return None
