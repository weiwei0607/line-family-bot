"""
Family bot horoscope handlers.
Single sign, all-family, and compatibility.
"""

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from entertainment_api import get_horoscope_round_robin, get_starmatch, SIGN_MAP
from api_helpers import smart_translate, call_gemini
from line_push import reply_text as reply


def _handle_horoscope(reply_token: str, text: str, member_signs: dict[str, str]) -> bool:
    """
    Handle horoscope commands: single sign, all-family, compatibility.
    member_signs: mapping of member name -> zodiac sign (e.g. {"爸爸": "摩羯"})
    Returns True if handled.
    """
    # ── 星座運勢 ──
    m = re.match(r"^(牡羊|金牛|雙子|巨蟹|獅子|處女|天秤|天蠍|射手|摩羯|水瓶|雙魚)座?運勢?$", text)
    if m:
        data = get_horoscope_round_robin(m.group(1))
        if data:
            desc = smart_translate(data["description"])
            source = data.get("source", "")
            source_tag = f"（{source}）" if source else ""
            reply(reply_token, f"✨ {data['sign']} 今日運勢{source_tag}\n\n{desc}\n\n"
                               f"心情：{data['mood']}　幸運色：{data['color']}\n"
                               f"幸運數字：{data['lucky_number']}　配對：{data['compatibility']}座")
        else:
            reply(reply_token, "星座資料取得失敗，待會再試試")
        return True

    if text == "星座":
        reply(reply_token, "請傳「[星座]運勢」\n例：天蠍座運勢、射手運勢")
        return True

    # ── 今日全員運勢 ──
    if text in ["今日全員運勢", "全員運勢", "大家的運勢", "家人運勢"]:
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(get_horoscope_round_robin, sign): name
                for name, sign in member_signs.items()
            }
            results = {}
            for future in as_completed(futures):
                name = futures[future]
                results[name] = future.result()

        def _translate_one(args):
            name, sign = args
            data = results.get(name)
            if data and data.get("description"):
                desc = call_gemini(f"翻成繁體中文1-2句：{data['description']}")
                return name, sign, desc, data.get("color", "—"), data.get("lucky_number", "—")
            return name, sign, None, "—", "—"

        with ThreadPoolExecutor(max_workers=4) as executor:
            translated = list(executor.map(_translate_one, member_signs.items()))

        lines = ["✨ 今日全家運勢\n"]
        for name, sign, desc, color, lucky in translated:
            if desc:
                lines.append(f"【{name}】{sign}座\n{desc}\n幸運色：{color}　數字：{lucky}\n")
            else:
                lines.append(f"【{name}】{sign}座\n（資料取得失敗）\n")
        reply(reply_token, "\n".join(lines))
        return True

    # ── 星座配對 ──
    m = re.match(r"^(牡羊|金牛|雙子|巨蟹|獅子|處女|天秤|天蠍|射手|摩羯|水瓶|雙魚)\s*配\s*(牡羊|金牛|雙子|巨蟹|獅子|處女|天秤|天蠍|射手|摩羯|水瓶|雙魚)$", text)
    if m:
        s1, s2 = m.group(1), m.group(2)
        data = get_starmatch(SIGN_MAP.get(s1, s1), SIGN_MAP.get(s2, s2))
        if data:
            desc_zh = smart_translate(data["description"])
            reply(reply_token, f"💖 {s1}座 × {s2}座 配對指數\n\n"
                               f"分數：{data['compatibility']}\n\n{desc_zh}")
        else:
            reply(reply_token, "配對資料取得失敗，待會再試試")
        return True

    if text == "配對":
        reply(reply_token, "請傳「[星座]配[星座]」\n例：天蠍配金牛、雙子配射手")
        return True

    return False
