"""Weather Api for line-family-bot."""

import re
import requests
from datetime import datetime, timedelta
import logging
__all__ = ['WMO', 'format_weather_block', 'format_weather_day', 'format_weather_rain_check', 'get_aqi', 'get_weather', 'get_weather_day', 'get_weather_forecast', 'logger', 'parse_date_offset']


logger = logging.getLogger(__name__)

from api_helpers import (
_retry_http, _cached, LAT, LON, WEATHER_CITY
)


WMO = {
    0: "☀️ 晴天", 1: "🌤 大致晴", 2: "⛅️ 部分多雲", 3: "☁️ 陰天",
    45: "🌫 有霧", 48: "🌫 有霧",
    51: "🌦 毛毛雨", 53: "🌦 毛毛雨", 55: "🌧 小雨",
    61: "🌧 小雨", 63: "🌧 中雨", 65: "🌧 大雨",
    71: "🌨 小雪", 73: "🌨 中雪", 75: "❄️ 大雪",
    80: "🌦 陣雨", 81: "🌧 陣雨", 82: "⛈ 大陣雨",
    95: "⛈ 雷雨", 96: "⛈ 雷雨夾冰雹", 99: "⛈ 雷雨夾冰雹",
}

_WEEKDAY_NAMES = ["一", "二", "三", "四", "五", "六", "日"]


def _get_uv_index() -> dict | None:
    """取得 UV 指數（Open-Meteo）"""


    try:
        r = requests.get(
            "https://air-quality-api.open-meteo.com/v1/air-quality",
            params={"latitude": LAT, "longitude": LON, "current": "uv_index", "timezone": "Asia/Taipei"},
            timeout=8,
        )
        d = r.json()
        uv = round(d["current"]["uv_index"], 1)
        if uv >= 8:
            level = "🔴 極高"
        elif uv >= 6:
            level = "🟠 高"
        elif uv >= 3:
            level = "🟡 中等"
        else:
            level = "🟢 低"
        return {"uv": uv, "level": level}
    except Exception:
        return None


def parse_date_offset(text: str) -> tuple[int, str] | None:
    """從中文文字解析日期偏移，回傳 (offset_days, 描述)"""
    text = text.replace(" ", "").replace("?", "").replace("？", "")

    # 今天
    if re.search(r"^(今天|今日|現在)", text) or text in ["今天", "今日"]:
        return (0, "今天")
    # 明天
    if re.search(r"^(明天|明日)", text) or text in ["明天", "明日"]:
        return (1, "明天")
    # 後天
    if re.search(r"^(後天)", text) or text in ["後天"]:
        return (2, "後天")
    # 大後天
    if re.search(r"^(大後天)", text) or text in ["大後天"]:
        return (3, "大後天")

    # 星期/週/禮拜/周
    weekday_map = {
        "一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5,
        "日": 6, "天": 6,
        "1": 0, "2": 1, "3": 2, "4": 3, "5": 4, "6": 5, "7": 6,
    }
    m = re.search(r"(下?[星期週禮礼拜周])([一二三四五六日天1234567])", text)
    if m:
        prefix = m.group(1)
        day_char = m.group(2)
        target = weekday_map.get(day_char)
        if target is not None:
            today = datetime.now().weekday()
            diff = (target - today) % 7
            is_next = prefix.startswith("下")
            if is_next:
                offset = diff + 7
            else:
                offset = diff
            name = _WEEKDAY_NAMES[target]
            desc = f"{'下週' if is_next else '本週'}星期{name}"
            return (offset, desc)

    return None


def _weather_advice(condition: str, rain_prob: int, temp_max: int) -> str:
    """根據天氣給出門建議"""
    advice = []
    if rain_prob >= 60:
        advice.append("☔ 記得帶傘！")
    elif rain_prob >= 30:
        advice.append("🌂 可能會下雨，建議帶傘")
    if "晴" in condition and temp_max >= 30:
        advice.append("🧴 天氣炎熱，記得擦防曬")
    elif "晴" in condition and temp_max >= 28:
        advice.append("🌞 天氣不錯，注意防曬")
    if temp_max <= 18:
        advice.append("🧥 氣溫較低，記得穿暖")
    return "\n".join(advice) if advice else ""

def get_weather_forecast() -> dict:
    """取得7天天氣預報 + 目前天氣"""
    def _fetch():
        try:
            r = requests.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": LAT, "longitude": LON,
                    "current": "temperature_2m,weathercode,relative_humidity_2m",
                    "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode",
                    "timezone": "Asia/Taipei", "forecast_days": 7,
                },
                timeout=10,
            )
            d = r.json()
            cur = d["current"]
            day = d["daily"]
            forecast = []
            for i in range(7):
                code = int(day.get("weathercode", [0]*7)[i])
                forecast.append({
                    "condition": WMO.get(code, "天氣不明"),
                    "temp_max": round(day["temperature_2m_max"][i]),
                    "temp_min": round(day["temperature_2m_min"][i]),
                    "rain_prob": round(day["precipitation_probability_max"][i]),
                })
            return {
                "current": {
                    "condition": WMO.get(int(cur.get("weathercode", 0)), "天氣不明"),
                    "temp": round(cur["temperature_2m"]),
                    "humidity": round(cur["relative_humidity_2m"]),
                },
                "forecast": forecast,
            }
        except Exception as e:
            return {"error": str(e)}
    return _cached("weather7", 1800, _fetch) or {"error": "無法取得天氣"}


def get_weather() -> dict:
    """兼容舊接口，回傳今天天氣"""
    f = get_weather_forecast()
    if "error" in f:
        return f
    today = f["forecast"][0].copy()
    today["temp"] = f["current"]["temp"]
    today["humidity"] = f["current"]["humidity"]
    return today


def get_weather_day(offset: int = 0) -> dict | None:
    """取得指定偏移日期的天氣"""
    f = get_weather_forecast()
    if "error" in f:
        return None
    if offset < 0 or offset >= len(f["forecast"]):
        return None
    return f["forecast"][offset]


def format_weather_day(offset: int = 0) -> str:
    """格式化指定日期的天氣"""
    day = get_weather_day(offset)
    if day is None:
        return "（天氣資料取得失敗）"
    target = datetime.now() + timedelta(days=offset)
    date_str = target.strftime("%m/%d")
    weekday = _WEEKDAY_NAMES[target.weekday()]
    advice = _weather_advice(day["condition"], day["rain_prob"], day["temp_max"])
    lines = [
        f"{day['condition']}　最高 {day['temp_max']}° / 最低 {day['temp_min']}°",
        f"降雨機率 {day['rain_prob']}%",
    ]
    if advice:
        lines.append(f"\n💡 出門建議：\n{advice}")
    return f"📅 {date_str}（{weekday}）\n" + "\n".join(lines)


def format_weather_rain_check(offset: int, desc: str) -> str:
    """回答「會不會下雨」"""
    day = get_weather_day(offset)
    if day is None:
        return "（天氣資料取得失敗）"
    if offset < 0 or offset >= 7:
        return f"❌ {desc} 超出7天預報範圍，目前只能查未來7天喔"
    target_date = (datetime.now() + timedelta(days=offset)).strftime("%m/%d")
    rain_prob = day["rain_prob"]
    if rain_prob >= 70:
        rain_msg = f"會下雨喔！🌧 降雨機率高達 {rain_prob}%"
    elif rain_prob >= 40:
        rain_msg = f"有可能會下雨 🌦 降雨機率 {rain_prob}%"
    elif rain_prob >= 20:
        rain_msg = f"有小機率下雨 ☁️ 降雨機率 {rain_prob}%"
    else:
        rain_msg = f"應該不會下雨 ☀️ 降雨機率只有 {rain_prob}%"
    advice = _weather_advice(day["condition"], day["rain_prob"], day["temp_max"])
    result = (
        f"📅 {desc}（{target_date}）\n"
        f"{rain_msg}\n"
        f"最高 {day['temp_max']}° / 最低 {day['temp_min']}°　{day['condition']}"
    )
    if advice:
        result += f"\n\n💡 出門建議：\n{advice}"
    return result


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
