"""
Family bot utility handlers.
Wikipedia, world time, country info, BMI, recipes, nutrition, calories, holidays.
"""

import re
from datetime import datetime as _dt
from zoneinfo import ZoneInfo as _ZoneInfo
_TW_TZ = _ZoneInfo("Asia/Taipei")
from api_helpers import (
    get_wikipedia, get_world_time, get_country_info,
    search_recipes_by_ingredients, get_nutrition, get_calories_burned,
    get_holidays, call_ai, calc_bmi, rewrite_text, fetch_youtube,
    check_grammar,
)
from line_push import reply_text as reply


def _handle_utils(reply_token: str, text: str) -> bool:
    """
    Handle utility commands: wiki, world time, country info, BMI,
    recipes, nutrition, calories burned, holidays.
    Returns True if handled.
    """
    # ── 維基百科 ──
    m = re.match(r"^(?:百科|維基|查一下|wiki)\s+(.+)$", text, re.IGNORECASE)
    if m:
        query = m.group(1).strip()
        info = get_wikipedia(query)
        if info and info.get("extract"):
            reply(reply_token, f"📖 {info['title']}\n\n{info['extract'][:300]}")
        else:
            reply(reply_token, f"📖 {query}\n\n{call_ai(f'用繁體中文簡短介紹「{query}」，2-3句。')}")
        return True

    # ── 世界時間 ──
    m = re.match(r"^(?:幾點了|現在幾點|時間)\s+(.+)$", text)
    if m:
        city = m.group(1).strip()
        info = get_world_time(city)
        if info:
            reply(reply_token, f"🕐 {city}現在時間\n\n{info['datetime']}")
        else:
            reply(reply_token, f"找不到「{city}」的時區，試試：東京、倫敦、紐約、曼谷")
        return True

    # ── 國家資訊 ──
    m = re.match(r"^(?:查國家|國家)\s+(.+)$", text)
    if m:
        name = m.group(1).strip()
        info = get_country_info(name)
        if info:
            pop = f"{info['population']:,}"
            area = f"{info['area']:,.0f}" if info.get("area") else "—"
            lines = [
                f"{info.get('flag', '')} {info['name']}\n",
                f"首都：{info['capital'] or '—'}",
                f"地區：{info['region']}",
                f"人口：{pop}",
                f"面積：{area} km²",
                f"語言：{info['languages'] or '—'}",
                f"貨幣：{info['currencies'] or '—'}",
            ]
            reply(reply_token, "\n".join(lines))
        else:
            reply(reply_token, f"找不到「{name}」的資料，試試英文名稱")
        return True

    # ── BMI ──
    m = re.match(r"^BMI\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)$", text, re.IGNORECASE)
    if m:
        h, w = float(m.group(1)), float(m.group(2))
        result = calc_bmi(h, w)
        reply(reply_token, f"⚖️ BMI 計算\n\n身高 {h}cm / 體重 {w}kg\n\nBMI：{result['bmi']}\n{result['category']}")
        return True

    if text in ["BMI", "計算BMI", "我的BMI"]:
        reply(reply_token, "請傳「BMI 身高 體重」\n例：BMI 165 55")
        return True

    # ── 食譜搜尋 ──
    m = re.match(r"^食譜\s+(.+)$", text)
    if m:
        results = search_recipes_by_ingredients(m.group(1).strip())
        if results:
            lines = [f"🍳 食譜推薦：\n"]
            for r in results[:3]:
                lines.append(f"• {r.get('title', '')}")
            reply(reply_token, "\n".join(lines))
        else:
            reply(reply_token, call_ai(f"根據食材「{m.group(1)}」推薦一道家常料理和做法"))
        return True

    # ── 熱量查詢 ──
    m = re.match(r"^熱量\s+(.+)$", text)
    if m:
        food = m.group(1).strip()
        items = get_nutrition(food)
        if items:
            lines = [f"🔥 熱量查詢：{food}\n"]
            for it in items[:3]:
                lines.append(
                    f"• {it.get('name','')}（{it.get('serving_size_g','')}g）"
                    f"：{round(it.get('calories',0))} 卡　"
                    f"蛋白質 {round(it.get('protein_g',0))}g　脂肪 {round(it.get('fat_total_g',0))}g"
                )
            reply(reply_token, "\n".join(lines))
        else:
            reply(reply_token, "查不到，試試英文食物名稱")
        return True

    # ── 消耗熱量 ──
    m = re.match(r"^消耗熱量\s+(.+?)(?:\s+(\d+)分鐘?)?$", text)
    if m:
        activity = m.group(1).strip()
        duration = int(m.group(2)) if m.group(2) else 30
        items = get_calories_burned(activity, duration_min=duration)
        if items:
            lines = [f"🏃 消耗熱量：{activity}（{duration}分鐘）\n"]
            for it in items[:3]:
                cal = it.get("calories_per_hour", 0)
                total = round(cal * duration / 60)
                lines.append(f"• {it.get('name', activity)}：約 {total} 卡")
            reply(reply_token, "\n".join(lines))
        else:
            reply(reply_token, call_ai(f"請告訴我做「{activity}」{duration}分鐘大約消耗多少卡路里"))
        return True

    # ── 找影片 ──
    m = re.match(r"^找影片\s+(.+)$", text)
    if m:
        reply(reply_token, fetch_youtube(m.group(1).strip()))
        return True

    # ── 改寫文案 ──
    m = re.match(r"^改寫\s+(.+)$", text, re.DOTALL)
    if m:
        result = rewrite_text(m.group(1).strip())
        if result:
            reply(reply_token, f"✍️ 改寫結果：\n\n{result}")
        else:
            reply(reply_token, "改寫服務暫時無法使用，請稍後再試")
        return True

    # ── 英文文法檢查 ──
    m = re.match(r"^(?:文法檢查|grammar)\s+(.+)$", text, re.IGNORECASE)
    if m:
        sentence = m.group(1).strip()
        result = check_grammar(sentence)
        if result and result.get("corrected"):
            errors = result.get("errors", [])
            if errors:
                err_lines = []
                for e in errors[:3]:
                    bad = e.get("bad", "")
                    better = e.get("better", [])
                    better_str = f"→ {' / '.join(better[:2])}" if better else ""
                    err_lines.append(f"• 「{bad}」{better_str}")
                reply(reply_token,
                      f"📝 文法檢查結果\n\n原文：{sentence}\n\n修正：{result['corrected']}\n\n問題：\n" + "\n".join(err_lines))
            else:
                reply(reply_token, f"📝 文法檢查結果\n\n原文：{sentence}\n\n✅ 沒有發現明顯錯誤")
        else:
            reply(reply_token, "文法檢查服務暫時無法使用，請稍後再試")
        return True

    # ── 節假日 ──
    m = re.match(r"^節日(?:\s+(\d{1,2})[/／](\d{1,2}))?$", text)
    if m or text in ["今天節日", "今日節日", "今天什麼節", "今天是什麼節日", "什麼節日"]:
        if m and m.group(1):
            month, day = int(m.group(1)), int(m.group(2))
            year = _dt.now().year
            holidays = get_holidays(year=year, month=month, day=day)
            date_str = f"{month}/{day}"
        else:
            now = _dt.now(_TW_TZ)
            holidays = get_holidays()
            date_str = f"{now.month}/{now.day}"
        if holidays:
            lines = [f"🎌 {date_str} 的節日\n"]
            for h in holidays:
                name = h.get("name", "")
                h_type = h.get("type", "")
                lines.append(f"• {name}（{h_type}）" if h_type else f"• {name}")
            reply(reply_token, "\n".join(lines))
        else:
            reply(reply_token, f"📅 {date_str} 沒有台灣國定假日")
        return True

    return False
