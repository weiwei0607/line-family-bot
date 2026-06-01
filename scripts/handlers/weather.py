"""Weather command handler."""

from line_push import reply_text as reply
from api_helpers import parse_date_offset, get_aqi, format_weather_day, format_weather_rain_check, format_weather_block


def _handle_weather(reply_token: str, text: str) -> bool:
    """Handle weather-related commands."""
    weather_triggers = ["天氣", "下雨", "會下雨", "帶傘", "氣溫", "溫度", "適合出門", "出門嗎"]
    has_weather_word = any(k in text for k in weather_triggers)
    date_result = parse_date_offset(text)
    is_weather_cmd = text in ["天氣", "今天天氣", "天氣如何", "外面天氣"]

    if is_weather_cmd or has_weather_word or (date_result and ("嗎" in text or "?" in text or "？" in text)):
        if date_result:
            offset, desc = date_result
            if offset >= 7:
                reply(reply_token, f"❌ {desc} 超出7天預報範圍，目前只能查未來7天喔")
                return True
            if any(k in text for k in ["下雨", "會不會", "帶傘", "雨"]):
                reply(reply_token, format_weather_rain_check(offset, desc))
            else:
                a = get_aqi()
                weather_text = format_weather_day(offset)
                if offset == 0 and "error" not in a:
                    weather_text += f"\n\n空氣品質 AQI {a['aqi']}（{a['level']}）PM2.5：{a['pm25']}"
                reply(reply_token, f"🌡 {desc}天氣\n\n{weather_text}")
        else:
            reply(reply_token, "🌡 今日天氣\n\n" + format_weather_block())
        return True
    return False
