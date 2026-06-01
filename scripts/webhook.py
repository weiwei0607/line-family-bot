"""
LINE 家庭群機器人 webhook
"""

import os
import re
import json
import difflib
import requests
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, TextMessage, ImageMessage,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, AudioMessageContent
from api_helpers import (
    format_weather_block, format_weather_day, format_weather_rain_check,
    parse_date_offset, get_advice, get_horoscope, get_fun_fact,
    search_recipes_by_ingredients, get_nutrition,
    get_joke, get_trivia, get_cocktail, get_random_activity,
    get_exercise, get_anime_quote, generate_image,
    get_currency, get_gold_price, get_movie, get_streaming, calc_bmi,
    get_chuck_norris, get_motivation_quote, get_movie_quote,
    get_astronomy_fact, get_calories_burned,
    get_jisho, get_kanji_info, get_random_jlpt_word,
    get_spanish_dict, get_meal_random, get_open_trivia, get_number_fact,
    get_nasa_apod, translate_text, smart_translate, text_to_speech, save_tts_audio, get_tts_audio,
    get_joke_round_robin, get_horoscope_round_robin, get_news_round_robin,
    get_starmatch, call_groq, groq_stt,
    JLPT_N5_KANJI, QUOTA_MSG, TMDB_KEY,
)

from sheets import (
    bg, get_members, get_chores, complete_chore, add_chore,
    get_weekly_points, format_weekly_summary, register_member,
    batch_log_points, get_shopping_list, add_shopping, complete_shopping,
    add_expense, get_expenses, get_member_weekly_breakdown,
    get_member_weekly_chore_points, WEEKLY_CAPS,
    add_declutter, get_declutter_list, complete_declutter,
    add_income, get_declutter_income, cancel_last_record,
    pay_fine, get_outstanding_fines,
)

app = Flask(__name__)

# 註冊 Daily Dose API
from dose_api import dose_bp
app.register_blueprint(dose_bp)

_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
_secret = os.environ.get("LINE_CHANNEL_SECRET", "")
configuration = Configuration(access_token=_token)
handler = WebhookHandler(_secret)
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
POINTS_THRESHOLD = int(os.environ.get("POINTS_THRESHOLD", "5"))

MEMBER_SIGNS = {
    "爸爸": "摩羯",
    "媽媽": "射手",
    "姊姊": "雙子",
    "妹妹": "金牛",
}

_quiz_state: dict[str, dict] = {}  # group_id -> {question, answer}

# ─── 工具函數 ─────────────────────────────────

def reply(reply_token: str, text: str):
    with ApiClient(configuration) as api_client:
        MessagingApi(api_client).reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=text[:4900])],
            )
        )

def reply_image(reply_token: str, image_url: str, fallback: str = "圖片生成失敗"):
    try:
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(
                ReplyMessageRequest(
                    reply_token=reply_token,
                    messages=[ImageMessage(
                        original_content_url=image_url,
                        preview_image_url=image_url,
                    )],
                )
            )
    except Exception:
        reply(reply_token, fallback)


from linebot.v3.messaging import AudioMessage

def reply_audio(reply_token: str, audio_url: str, duration: int = 5000, fallback: str = "語音發送失敗"):
    """發送語音訊息（duration 單位：毫秒）"""
    try:
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(
                ReplyMessageRequest(
                    reply_token=reply_token,
                    messages=[AudioMessage(
                        original_content_url=audio_url,
                        duration=duration,
                    )],
                )
            )
    except Exception:
        reply(reply_token, fallback)


# ── TTS 音檔公開路由 ───────────────────────────

@app.route("/tts/<filename>")
def serve_tts(filename: str):
    data = get_tts_audio(filename)
    if not data:
        abort(404)
    from flask import Response
    return Response(data[0], mimetype=data[1])


def reply_image_with_text(reply_token: str, image_url: str, text: str):
    try:
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(
                ReplyMessageRequest(
                    reply_token=reply_token,
                    messages=[
                        ImageMessage(original_content_url=image_url, preview_image_url=image_url),
                        TextMessage(text=text[:4900]),
                    ],
                )
            )
    except Exception:
        reply(reply_token, text)


def _q(val, reply_token: str) -> bool:
    """如果 val 是 quota exceeded 標記，回覆錯誤訊息並回傳 True。"""
    if val == QUOTA_MSG:
        reply(reply_token, QUOTA_MSG)
        return True
    if isinstance(val, dict) and val.get("_quota"):
        reply(reply_token, QUOTA_MSG)
        return True
    if isinstance(val, list) and val and isinstance(val[0], dict) and val[0].get("_quota"):
        reply(reply_token, QUOTA_MSG)
        return True
    return False


def _send_movie(reply_token: str, movie: dict):
    """發送電影資訊，TMDB 版有海報圖片。"""
    if movie.get("_tmdb"):
        title = movie.get("title", "")
        orig = movie.get("original_title", "")
        year = movie.get("year", "")
        rating = movie.get("rating", "")
        overview = movie.get("overview", "") or ""
        caption = (f"🎬 {title}"
                   + (f"（{orig}）" if orig and orig != title else "")
                   + (f"  {year}\n" if year else "\n")
                   + f"⭐ {rating} 分\n\n"
                   + overview[:200])
        poster = movie.get("poster_url")
        if poster:
            reply_image_with_text(reply_token, poster, caption)
        else:
            reply(reply_token, caption)
    else:
        reply(reply_token, f"🎬 {movie.get('title', '')}（{movie.get('year', '')}）\n\n"
                           f"⭐ {movie.get('rating', '')}　排名第 {movie.get('rank', '')} 名\n\n"
                           f"{movie.get('description', '')[:150]}")


def call_gemini(prompt: str) -> str:
    if not GEMINI_KEY:
        return call_groq(prompt) or "（需要設定 GEMINI_API_KEY 或 GROQ_API_KEY）"
    try:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/"
            f"models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
        )
        resp = requests.post(
            url,
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=20,
        )
        if resp.status_code == 429:
            return call_groq(prompt) or "AI 額度已達上限，請稍後再試"
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception:
        return call_groq(prompt) or "AI 暫時無法回應"

# ─── 指令處理 ─────────────────────────────────

def handle_chores(reply_token: str, member: str, text: str):
    """處理家事相關指令"""
    m = re.match(r"^(完成|做了|做好了|完成了)\s*(.+)", text)
    if m:
        chore_name = m.group(2).strip()
        result = complete_chore(chore_name, member or "不知道誰")
        if result and result.get("capped"):
            reply(reply_token,
                  f"⚠️ {member or '你'} 本週「{result['name']}」已達上限 {result['cap']} 點，不再計分喔！")
        elif result:
            pts = result["points"]
            pts_str = f"{pts:.2f}".rstrip('0').rstrip('.')
            summary = format_weekly_summary()
            reply(reply_token,
                  f"✅ {member or '你'} 完成了「{result['name']}」！獲得 {pts_str} 點 🎉\n\n{summary}")
        else:
            reply(reply_token,
                  f"找不到「{chore_name}」這個家事耶，確認一下名稱是否正確？\n"
                  f"輸入「家事清單」看看所有家事")
        return True

    if text in ["家事清單", "家事", "待完成", "還有什麼家事"]:
        chores = get_chores()
        if not chores:
            reply(reply_token, "🎉 家事清單是空的！")
        else:
            lines = ["📋 家事清單：\n"]
            for c in chores:
                cap = WEEKLY_CAPS.get(c['name'])
                cap_str = f"（上限{cap}點/週）" if cap else ""
                lines.append(f"• {c['name']}  {c['points']}點{cap_str}")
            reply(reply_token, "\n".join(lines))
        return True

    m = re.match(r"^新增家事\s+(.+?)(\s+(\d+(?:\.\d+)?)點?)?$", text)
    if m:
        name = m.group(1).strip()
        pts = float(m.group(3)) if m.group(3) else 1
        bg(add_chore, name, pts)
        pts_str = f"{pts:.2f}".rstrip('0').rstrip('.')
        reply(reply_token, f"✅ 新增家事「{name}」（{pts_str}點），大家加油！")
        return True

    return False


def handle_points(reply_token: str, member: str, text: str):
    """查詢點數"""
    if text in ["點數", "查點數", "點數排行", "積分", "本週點數"]:
        pts = get_weekly_points()
        members = get_members()
        lines = ["🏆 本週家事點數：\n"]
        for m in members:
            p = pts.get(m, 0)
            p_str = f"{p:.2f}".rstrip('0').rstrip('.')
            warn = " ⚠️ 未達標" if p < POINTS_THRESHOLD else " ✅"
            lines.append(f"{m}：{p_str} 點{warn}")
        lines.append(f"\n（目標：每週 {POINTS_THRESHOLD} 點以上）")
        reply(reply_token, "\n".join(lines))
        return True

    if text in ["我的點數", "我的紀錄", "我做了什麼", "我的家事"]:
        if not member:
            reply(reply_token, "還不知道你是誰，先傳「我是＿＿」讓我記住你 😊")
            return True
        breakdown = get_member_weekly_breakdown(member)
        total = sum(d["points"] for d in breakdown)
        total_str = f"{total:.2f}".rstrip('0').rstrip('.')
        if not breakdown:
            reply(reply_token, f"{member} 本週還沒有記錄，快去做家事！💪")
        else:
            lines = [f"📋 {member} 本週家事：\n"]
            for d in breakdown:
                p_str = f"{d['points']:.2f}".rstrip('0').rstrip('.')
                lines.append(f"• {d['name']}  {p_str}點")
            lines.append(f"\n合計：{total_str} 點")
            status = "✅ 已達標" if total >= POINTS_THRESHOLD else f"⚠️ 距目標還差 {POINTS_THRESHOLD - total:.2f}".rstrip('0').rstrip('.') + " 點"
            lines.append(status)
            reply(reply_token, "\n".join(lines))
        return True

    # 取消記錄
    m = re.match(r"^取消記錄\s*(.*)$", text)
    if m or text in ["取消上筆", "取消記錄"]:
        if not member:
            reply(reply_token, "還不知道你是誰，先傳「我是＿＿」讓我記住你 😊")
            return True
        chore_name = m.group(1).strip() if m and m.group(1).strip() else None
        result = cancel_last_record(member, chore_name)
        if result:
            p_str = f"{result['points']:.2f}".rstrip('0').rstrip('.')
            reply(reply_token, f"✅ 已取消「{result['name']}」的 {p_str} 點記錄")
        else:
            tip = f"「{chore_name}」的" if chore_name else ""
            reply(reply_token, f"找不到{tip}記錄，沒有東西可以取消")
        return True

    return False


def handle_shopping(reply_token: str, member: str, text: str):
    """購物清單指令"""
    m = re.match(r"^(加購物|要買|買|購物加)\s+(.+)", text)
    if m:
        item = m.group(2).strip()
        bg(add_shopping, item, member or "")
        reply(reply_token, f"🛒 已加入購物清單：{item}")
        return True

    m = re.match(r"^(買好了|已買|買到了|買了)\s+(.+)", text)
    if m:
        item = m.group(2).strip()
        ok = complete_shopping(item, member or "")
        if ok:
            reply(reply_token, f"✅ 已標記「{item}」已購買 🛒")
        else:
            reply(reply_token, f"找不到「{item}」在購物清單裡喔")
        return True

    if text in ["購物清單", "要買什麼"]:
        items = get_shopping_list(only_pending=True)
        if not items:
            reply(reply_token, "🛒 購物清單是空的！")
        else:
            lines = ["🛒 待購物清單：\n"]
            for it in items:
                lines.append(f"• {it['name']}（{it['added_by']} 加的）")
            reply(reply_token, "\n".join(lines))
        return True

    return False


def handle_accounting(reply_token: str, member: str, text: str):
    """家庭記帳"""
    m = re.match(r"^記帳\s+(\d+)\s+(.+?)(?:\s+(.+))?$", text)
    if m:
        amount = int(m.group(1))
        part2 = m.group(2).strip()
        part3 = m.group(3).strip() if m.group(3) else ""
        if part3:
            category, desc = part2, part3
        else:
            category, desc = "雜費", part2
        bg(add_expense, amount, category, desc, member or "")
        reply(reply_token,
              f"💰 已記帳：{category} - {desc}，{amount} 元\n（{member or ''}）")
        return True

    if text in ["帳", "帳目", "今日帳", "本週帳", "查帳"]:
        days = 1 if "今日" in text else 7
        exps = get_expenses(days=days)
        if not exps:
            reply(reply_token, f"最近 {days} 天沒有記帳紀錄")
        else:
            total = sum(e["amount"] for e in exps)
            label = "今日" if days == 1 else "最近7天"
            lines = [f"💰 {label}支出（共 {total} 元）：\n"]
            for e in exps[-10:]:
                lines.append(f"• {e['date']} {e['category']} {e['desc']} {e['amount']}元（{e['by']}）")
            reply(reply_token, "\n".join(lines))
        return True

    return False


def handle_fine(reply_token: str, member: str, text: str) -> bool:
    """罰款與欠款指令"""
    m = re.match(r"^繳罰款\s+(\d+)$", text)
    if m:
        if not member:
            reply(reply_token, "還不知道你是誰，先傳「我是＿＿」😊")
            return True
        amount = int(m.group(1))
        pay_fine(member, amount)
        balances = get_outstanding_fines(member=member)
        remaining = balances.get(member, 0)
        if remaining <= 0:
            reply(reply_token, f"✅ {member} 已繳 {amount} 元，欠款清零！小本本乾淨了 🎉")
        else:
            reply(reply_token, f"✅ {member} 已繳 {amount} 元，還欠 {remaining} 元")
        return True

    if text in ["欠款", "欠款清單", "小本本"]:
        balances = get_outstanding_fines()
        if not balances:
            reply(reply_token, "📒 小本本是空的，大家都沒有欠款 🎉")
        else:
            lines = ["📒 欠款小本本：\n"]
            for m_name, total in balances.items():
                if total > 0:
                    lines.append(f"  {m_name}：欠 {total} 元")
                elif total < 0:
                    lines.append(f"  {m_name}：多繳了 {-total} 元")
            lines.append("\n投幣後傳「繳罰款 金額」登記")
            reply(reply_token, "\n".join(lines))
        return True

    return False


def handle_declutter(reply_token: str, member: str, text: str) -> bool:
    """斷捨離指令"""
    # 加入待定區
    m = re.match(r"^斷捨離\s+(.+)", text)
    if m and text not in ["斷捨離清單", "斷捨離收入"]:
        item = m.group(1).strip()
        bg(add_declutter, item, member or "")
        reply(reply_token, f"🗂️ 「{item}」已加入待定區\n確定要處理時傳「丟了 {item}」或「賣了 {item} 金額」")
        return True

    # 查待定清單
    if text == "斷捨離清單":
        items = get_declutter_list(only_pending=True)
        if not items:
            reply(reply_token, "🎉 待定區是空的，家裡很清爽！")
        else:
            lines = [f"🗂️ 斷捨離待定區（{len(items)} 項）：\n"]
            for it in items:
                lines.append(f"• {it['name']}（{it['added_by']} 加的）")
            lines.append("\n傳「丟了 物品名」或「賣了 物品名 金額」來處理")
            reply(reply_token, "\n".join(lines))
        return True

    # 丟棄
    m = re.match(r"^丟了\s+(.+)", text)
    if m:
        item = m.group(1).strip()
        result = complete_declutter(item, "丟棄", member or "")
        if result:
            reply(reply_token, f"🗑️ 「{item}」已丟棄！斷捨離成功 ✨")
        else:
            reply(reply_token, f"找不到「{item}」在待定區，先傳「斷捨離 {item}」加進去")
        return True

    # 賣出（帶金額）
    m = re.match(r"^賣了\s+(.+?)\s+(\d+)$", text)
    if m:
        item = m.group(1).strip()
        amount = int(m.group(2))
        result = complete_declutter(item, "賣出", member or "", amount)
        if result:
            bg(add_income, amount, f"賣掉：{item}", member or "")
            reply(reply_token, f"💰 「{item}」賣出 {amount} 元！\n已自動記入家庭帳本（斷捨離收入）✨")
        else:
            reply(reply_token, f"找不到「{item}」在待定區，先傳「斷捨離 {item}」加進去")
        return True

    # 賣出（沒帶金額）
    m = re.match(r"^賣了\s+(.+)", text)
    if m:
        item = m.group(1).strip()
        reply(reply_token, f"「{item}」賣了多少錢？請傳完整格式：\n「賣了 {item} 金額」")
        return True

    # 查斷捨離收入
    if text == "斷捨離收入":
        records = get_declutter_income()
        if not records:
            reply(reply_token, "目前還沒有斷捨離收入記錄")
        else:
            total = sum(r["amount"] for r in records)
            lines = [f"💰 斷捨離收入（共 {total} 元）：\n"]
            for r in records[-10:]:
                lines.append(f"• {r['date']} {r['desc']} {r['amount']}元（{r['by']}）")
            reply(reply_token, "\n".join(lines))
        return True

    return False


def handle_fun(reply_token: str, source, text: str) -> bool:

    group_id = getattr(source, "group_id", None) or getattr(source, "room_id", "default")

    # ── 天氣 ──
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

    # ── 今天吃什麼 ──
    if text in ["今天吃什麼", "吃什麼", "晚餐吃什麼", "午餐吃什麼"]:
        meal = get_meal_random()
        if meal:
            name_zh = smart_translate(meal["name"])
            ingr = "、".join(meal["ingredients"][:6])
            ingr_zh = smart_translate(ingr)
            lines = [f"🍽 今天來做：{name_zh}（{meal['area']} 料理）\n",
                     f"食材：{ingr_zh}"]
            if meal.get("youtube"):
                lines.append(f"\n▶️ 做法影片：{meal['youtube']}")
            reply(reply_token, "\n".join(lines))
        else:
            reply(reply_token, call_gemini(
                "隨機推薦一道台灣家常料理，格式：\n🍽 [菜名]\n食材：xxx\n做法：xxx（一句話）"
            ))
        return True

    # ── 星座運勢（輪班：Aztro → Daily Advanced → Daily Basic → Rashifal → Horostory → Astrologer）──
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
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(get_horoscope_round_robin, sign): name
                for name, sign in MEMBER_SIGNS.items()
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
            translated = list(executor.map(_translate_one, MEMBER_SIGNS.items()))

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

    # ── 問答遊戲 出題 ──
    if text in ["出題", "來玩問答", "問答遊戲", "出一題"]:
        trivia = get_open_trivia() or get_trivia()
        if trivia and trivia.get("question"):
            q_zh = smart_translate(trivia["question"])
            a_zh = smart_translate(trivia["answer"])
            _quiz_state[group_id] = {"question": q_zh, "answer": a_zh}
            reply(reply_token, f"🧠 問答時間！\n\n{q_zh}\n\n傳「答 你的答案」作答，傳「答案」看解答")
        else:
            qa = call_gemini("出一道適合全家的中文知識問答，格式：\n問題：xxx\n答案：xxx\n只給這兩行")
            question, answer = "", ""
            for line in qa.strip().splitlines():
                if line.startswith("問題："):
                    question = line[3:].strip()
                elif line.startswith("答案："):
                    answer = line[3:].strip()
            if question and answer:
                _quiz_state[group_id] = {"question": question, "answer": answer}
                reply(reply_token, f"🧠 問答時間！\n\n{question}\n\n傳「答 你的答案」作答，傳「答案」看解答")
            else:
                reply(reply_token, "出題失敗，再試一次！")
        return True

    # ── 問答遊戲 作答 ──
    m_ans = re.match(r"^答\s+(.+)$", text)
    if m_ans:
        if group_id not in _quiz_state:
            reply(reply_token, "目前沒有進行中的題目，傳「出題」開始！")
            return True
        state = _quiz_state[group_id]
        user_ans = m_ans.group(1).strip().lower()
        correct = state["answer"].lower()
        if correct in user_ans or user_ans in correct:
            del _quiz_state[group_id]
            reply(reply_token, f"🎉 答對了！答案是：{state['answer']}")
        else:
            reply(reply_token, "❌ 不對喔，再想想！")
        return True

    # ── 問答遊戲 看答案 ──
    if text in ["答案", "我不知道", "放棄", "答案是什麼"]:
        if group_id in _quiz_state:
            state = _quiz_state.pop(group_id)
            reply(reply_token, f"💡 答案是：{state['answer']}")
            return True

    # ── 笑話（輪班：JokeAPI → Dad Jokes → World of Jokes → Humor Jokes → DaddyJokes → Chuck Norris）──
    if text in ["笑話", "說個笑話", "講個笑話"]:
        joke = get_joke_round_robin()
        if _q(joke, reply_token): return True
        if joke and any(ord(c) > 127 for c in joke[:20]):
            reply(reply_token, f"😂 {joke}")
        elif joke:
            joke_zh = smart_translate(joke)
            reply(reply_token, f"😂 {joke_zh}")
        else:
            reply(reply_token, call_gemini("說一個適合全家的台灣笑話"))
        return True

    # ── 推薦飲料 ──
    m = re.match(r"^(?:推薦飲料|飲料)\s*(.*)$", text)
    if m:
        name = m.group(1).strip()
        data = get_cocktail(name)
        if data:
            ingr = "、".join(data.get("ingredients", [])[:5])
            instr_raw = (data.get("instructions") or "")[:250]
            instr = smart_translate(instr_raw)
            reply(reply_token, f"🍹 {data.get('name', '')}\n\n食材：{ingr}\n\n{instr}")
        else:
            reply(reply_token, call_gemini("推薦一款適合家庭的飲料或果汁，給出名稱和簡單做法"))
        return True

    # ── 今天做什麼 ──
    if text in ["今天做什麼", "無聊", "推薦活動", "隨機活動"]:
        data = get_random_activity()
        if data and data.get("activity"):
            act_zh = smart_translate(data["activity"])
            reply(reply_token, f"🎯 今天來試試：\n\n{act_zh}\n\n（適合 {data.get('participants','?')} 人）")
        else:
            reply(reply_token, call_gemini("推薦一個適合全家一起做的休閒活動，用繁體中文回答"))
        return True

    # ── 今天運動 ──
    if text in ["今天運動", "運動建議", "健身建議"]:
        data = get_exercise()
        if data:
            name_zh = smart_translate(data.get("name",""))
            body_zh = smart_translate(data.get("bodyPart",""))
            equip_zh = smart_translate(data.get("equipment",""))
            reply(reply_token, f"💪 今日運動：{name_zh}\n\n部位：{body_zh}\n器材：{equip_zh}")
        else:
            reply(reply_token, call_gemini("推薦一個適合在家做的簡單運動，說明動作和次數"))
        return True

    # ── 動漫名言 ──
    if text in ["動漫名言", "動漫語錄", "今日動漫"]:
        data = get_anime_quote()
        if data and data.get("quote"):
            quote = data.get("quote", "")
            anime = data.get("anime", "")
            char = data.get("character", "")
            quote_zh = smart_translate(quote)
            reply(reply_token, f"🌸 {quote_zh}\n\n—《{anime}》{char}")
        else:
            reply(reply_token, call_gemini("給我一句著名動漫台詞，說出出自哪部作品"))
        return True

    # ── 小花畫圖（Pollinations.ai，免費無限）──
    m = re.match(r"^(?:小花畫|畫)\s+(.+)$", text)
    if m:
        prompt = m.group(1).strip()
        url = generate_image(prompt)
        if url:
            reply_image(reply_token, url)
        else:
            reply(reply_token, "🎨 圖片生成失敗，請再試一次")
        return True

    # ── 匯率 ──
    m = re.match(r"^匯率\s+(\S+)(?:\s+(\S+))?$", text)
    if m:
        from_c, to_c = m.group(1), m.group(2) or "TWD"
        result = get_currency(from_c, to_c)
        if _q(result, reply_token): return True
        if result and result.get("rate"):
            reply(reply_token, f"💱 匯率\n\n1 {result['from']} = {result['rate']} {result['to']}")
        else:
            reply(reply_token, "匯率查詢失敗，請確認幣別代碼（如 USD JPY EUR）")
        return True

    # ── 金價 ──
    if text in ["金價", "今日金價", "黃金價格"]:
        data = get_gold_price()
        if _q(data, reply_token): return True
        if data and data.get("gold_usd"):
            twd = get_currency("USD", "TWD")
            rate = twd["rate"] if twd and twd.get("rate") and not twd.get("_quota") else 31
            gold_twd = round(float(data["gold_usd"]) * rate)
            lines = [
                f"🪙 今日金價\n",
                f"黃金：${data['gold_usd']} USD/盎司",
                f"約 NT$ {gold_twd:,} 元/盎司",
            ]
            if data.get("silver_usd"):
                lines.append(f"白銀：${data['silver_usd']} USD/盎司")
            reply(reply_token, "\n".join(lines))
        else:
            reply(reply_token, "金價查詢失敗，請稍後再試")
        return True

    # ── 電影 ──
    if text in ["推薦電影", "今晚看什麼", "電影推薦", "看電影"]:
        movie = get_movie()
        if _q(movie, reply_token): return True
        if movie:
            _send_movie(reply_token, movie)
        else:
            reply(reply_token, call_gemini("推薦一部適合全家看的電影，給出片名、年份、一句理由"))
        return True

    m = re.match(r"^電影\s+(.+)$", text)
    if m:
        title = m.group(1).strip()
        movie = get_movie(title)
        if _q(movie, reply_token): return True
        if movie:
            _send_movie(reply_token, movie)
        else:
            reply(reply_token, f"找不到「{title}」，試試其他關鍵字")
        return True

    # ── 哪裡看 ──
    m = re.match(r"^哪裡看\s+(.+)$", text)
    if m:
        title = m.group(1).strip()
        opts = get_streaming(title)
        if _q(opts, reply_token): return True
        if opts:
            type_zh = {"flatrate": "訂閱", "free": "免費", "rent": "租借", "buy": "購買"}
            lines = [f"📺 「{title}」台灣可觀看平台：\n"]
            for o in opts:
                t = type_zh.get(o.get("type", ""), "")
                lines.append(f"• {o['service']}" + (f"（{t}）" if t else ""))
            reply(reply_token, "\n".join(lines))
        else:
            reply(reply_token, f"找不到「{title}」在台灣的串流資訊")
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
            reply(reply_token, call_gemini(f"根據食材「{m.group(1)}」推薦一道家常料理和做法"))
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

    # ── 冷知識 ──
    if text in ["冷知識", "今日冷知識", "告訴我一件事"]:
        fact_en = get_fun_fact()
        if fact_en:
            reply(reply_token, f"🤓 冷知識\n\n{smart_translate(fact_en)}")
        else:
            reply(reply_token, call_gemini("給我一個有趣的冷知識，用繁體中文"))
        return True

    # ── 人生建議 ──
    if text in ["給我建議", "人生建議", "今日建議", "金玉良言"]:
        advice_en = get_advice()
        if advice_en:
            translated = smart_translate(advice_en)
            reply(reply_token, f"💡 {translated}\n\n（{advice_en}）")
        else:
            reply(reply_token, "今天沒有建議，就靠自己吧！")
        return True

    # ── 激勵名言 ──
    if text in ["激勵名言", "給我力量", "今日名言", "名言"]:
        q = get_motivation_quote()
        if q and q.get("text"):
            translated = smart_translate(q["text"])
            reply(reply_token, f"✨ {translated}\n\n— {q['author']}")
        else:
            reply(reply_token, call_gemini("給我一句激勵人心的名言，用繁體中文"))
        return True

    # ── 電影台詞 ──
    if text in ["電影台詞", "名片台詞", "電影名言"]:
        q = get_movie_quote()
        if q and q.get("quote"):
            quote_zh = smart_translate(q["quote"])
            reply(reply_token, f"🎬 「{quote_zh}」\n\n—《{q['movie']}》{q['character']}")
        else:
            reply(reply_token, call_gemini("給我一句著名電影台詞，說出電影名稱，用繁體中文"))
        return True

    # ── 天文冷知識 ──
    if text in ["天文冷知識", "科學冷知識", "宇宙冷知識"]:
        fact_en = get_astronomy_fact()
        if fact_en:
            reply(reply_token, f"🔭 {smart_translate(fact_en)}")
        else:
            reply(reply_token, call_gemini("給我一個有趣的天文或科學冷知識，用繁體中文"))
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
            reply(reply_token, call_gemini(f"請告訴我做「{activity}」{duration}分鐘大約消耗多少卡路里"))
        return True

    # ── NASA 每日天文圖 ──
    if text in ["今日宇宙", "宇宙圖片", "NASA", "天文圖", "宇宙"]:
        apod = get_nasa_apod()
        if _q(apod, reply_token): return True
        if apod and apod.get("_error"):
            reply(reply_token, f"🌌 {apod['_error']}")
            return True
        if apod:
            title_zh = smart_translate(apod['title'])
            explain_zh = call_gemini(
                f"翻成繁體中文，100字以內，保持有趣：{apod['explanation']}"
            )
            caption = f"🔭 {title_zh}（{apod['date']}）\n\n{explain_zh}"
            if apod["media_type"] == "image" and apod.get("hdurl"):
                reply_image_with_text(reply_token, apod["hdurl"], caption)
            else:
                reply(reply_token, caption + (f"\n\n▶️ {apod['url']}" if apod.get("url") else ""))
        else:
            reply(reply_token, "🌌 NASA 暫時無法連線，請稍後再試")
        return True

    # ── Chuck Norris ──
    if text in ["Chuck Norris", "查克諾里斯", "功夫笑話"]:
        joke_en = get_chuck_norris()
        if joke_en:
            joke_zh = smart_translate(joke_en)
            reply(reply_token, f"💪 {joke_zh}")
        else:
            reply(reply_token, call_gemini("說一個關於超強壯男人的誇張笑話，用繁體中文"))
        return True

    # ── 日文查詢 ──
    m = re.match(r"^(?:日文|查日文|日語)\s+(.+)$", text)
    if m:
        word = m.group(1).strip()
        data = get_jisho(word)
        if data:
            jlpt = f"  JLPT {data['jlpt'][0].upper()}" if data.get("jlpt") else ""
            common = "  ★常用" if data.get("common") else ""
            meanings_zh = smart_translate(", ".join(data["meanings_en"]))
            lines = [f"🇯🇵 {data['word']}（{data['reading']}）{jlpt}{common}\n",
                     f"意思：{meanings_zh}"]
            reply(reply_token, "\n".join(lines))
        else:
            reply(reply_token, call_gemini(f"用繁體中文解釋日文單字「{word}」的意思和讀音"))
        return True

    # ── 今日日文單字 ──
    if text in ["今日日文單字", "日文單字", "學日文"]:
        data = get_random_jlpt_word()
        if data:
            jlpt = f"JLPT {data['jlpt'][0].upper()}" if data.get("jlpt") else "N5"
            meanings_zh = smart_translate(", ".join(data["meanings_en"]))
            reply(reply_token,
                  f"📖 今日日文單字（{jlpt}）\n\n"
                  f"✏️ {data['word']}　読み：{data['reading']}\n"
                  f"意思：{meanings_zh}\n\n"
                  f"試著造個句子看看！")
        else:
            reply(reply_token, call_gemini(
                "給我一個 JLPT N5 等級的日文單字，包含：單字、假名讀音、繁體中文意思、一個例句"
            ))
        return True

    # ── 漢字查詢 ──
    m = re.match(r"^漢字\s+([^\s])$", text)
    if m:
        char = m.group(1)
        data = get_kanji_info(char)
        if data:
            jlpt = f"JLPT N{data['jlpt']}" if data.get("jlpt") else "—"
            on = "、".join(data["on_readings"]) or "—"
            kun = "、".join(data["kun_readings"]) or "—"
            meanings = "、".join(data["meanings"]) or "—"
            reply(reply_token,
                  f"🈶 漢字：{data['kanji']}\n\n"
                  f"音讀：{on}\n"
                  f"訓讀：{kun}\n"
                  f"意思：{meanings}\n"
                  f"筆畫：{data['stroke_count']}　{jlpt}")
        else:
            reply(reply_token, call_gemini(f"用繁體中文解釋日文漢字「{char}」的讀音和意思"))
        return True

    # ── 今日漢字 ──
    if text in ["今日漢字", "隨機漢字", "學漢字"]:
        import random as _r
        char = _r.choice(JLPT_N5_KANJI)
        data = get_kanji_info(char)
        if data:
            jlpt = f"JLPT N{data['jlpt']}" if data.get("jlpt") else "N5"
            on = "、".join(data["on_readings"]) or "—"
            kun = "、".join(data["kun_readings"]) or "—"
            meanings = "、".join(data["meanings"]) or "—"
            example = call_gemini(f"用「{char}」造一個簡單的日文例句，附上假名讀音和繁體中文翻譯")
            reply(reply_token,
                  f"🈶 今日漢字：{data['kanji']}（{jlpt}）\n\n"
                  f"音讀：{on}\n訓讀：{kun}\n意思：{meanings}\n"
                  f"筆畫：{data['stroke_count']}\n\n"
                  f"例句：\n{example}")
        else:
            reply(reply_token, call_gemini(
                f"用繁體中文介紹日文漢字「{char}」，包含讀音、意思和一個例句"
            ))
        return True

    # ── 西班牙文查詢 ──
    m = re.match(r"^(?:西文|查西文|西班牙文)\s+(.+)$", text)
    if m:
        word = m.group(1).strip()
        data = get_spanish_dict(word)
        if data and data.get("definitions"):
            defs = "\n".join(f"• {d}" for d in data["definitions"])
            phonetic = f"  [{data['phonetic']}]" if data.get("phonetic") else ""
            defs_zh = smart_translate(defs)
            reply(reply_token,
                  f"🇪🇸 {data['word']}{phonetic}\n\n{defs_zh}")
        else:
            reply(reply_token, call_gemini(
                f"用繁體中文解釋西班牙文單字「{word}」的意思、詞性和一個例句"
            ))
        return True

    # ── 今日西文單字 ──
    if text in ["今日西文單字", "西文單字", "學西文", "學西班牙文"]:
        reply(reply_token, call_gemini(
            "給我一個 A1-A2 等級的西班牙文單字，格式：\n"
            "📖 單字：xxx\n"
            "詞性：xxx\n"
            "中文意思：xxx\n"
            "例句：xxx（附中文翻譯）\n"
            "記憶技巧：xxx（一句話）"
        ))
        return True

    # ── 數字冷知識 ──
    if text in ["數字冷知識", "數字趣聞"]:
        fact_en = get_number_fact()
        if fact_en:
            reply(reply_token, f"🔢 {smart_translate(fact_en)}")
        else:
            reply(reply_token, call_gemini("給我一個關於數字的有趣冷知識，用繁體中文"))
        return True

    # ── 翻譯 ──
    m = re.match(r"^(?:翻譯|翻|translate)\s*(?:成?([\w\-]+)\s+)?(.+)", text, re.IGNORECASE)
    if m and m.group(2):
        target = (m.group(1) or "zh-TW").strip().lower()
        to_translate = m.group(2).strip()
        lang_aliases = {
            "中文": "zh-TW", "繁中": "zh-TW", "繁體中文": "zh-TW",
            "簡中": "zh-CN", "簡體中文": "zh-CN",
            "英文": "en", "英": "en", "english": "en",
            "日文": "ja", "日": "ja", "japanese": "ja",
            "韓文": "ko", "韓": "ko", "korean": "ko",
            "西文": "es", "西班牙文": "es", "spanish": "es",
            "法文": "fr", "法": "fr", "french": "fr",
            "德文": "de", "德": "de", "german": "de",
            "泰文": "th", "泰": "th", "thai": "th",
            "越文": "vi", "越南文": "vi", "vietnamese": "vi",
            "印尼文": "id", "indonesian": "id",
        }
        target = lang_aliases.get(target, target)
        lang_display = {
            "zh-TW": "繁體中文", "zh-CN": "簡體中文", "en": "英文",
            "ja": "日文", "ko": "韓文", "es": "西班牙文", "fr": "法文",
            "de": "德文", "th": "泰文", "vi": "越南文", "id": "印尼文",
        }.get(target, target)
        result = translate_text(to_translate, target)
        reply(reply_token, f"🌐 {lang_display}翻譯：\n\n{result}")
        return True

    if text in ["翻譯", "translate"]:
        reply(reply_token, "請傳「翻譯 [文字]」或「翻譯成英文 [文字]」\n例：翻譯成日文 你好")
        return True

    # ── 今日新聞 ──
    if text in ["新聞", "今日新聞", "頭條", "今天新聞"]:
        items = get_news_round_robin()
        if items:
            lines = ["📰 今日頭條\n"]
            for i, it in enumerate(items[:5], 1):
                title = it.get("title", "")
                lines.append(f"{i}. {title}")
            reply(reply_token, "\n".join(lines))
        else:
            reply(reply_token, "新聞取得失敗，待會再試")
        return True

    # ── 念出來（TTS）──
    m = re.match(r"^(?:念|唸|說|讀)\s+(.+)", text)
    if m:
        to_speak = m.group(1).strip()
        tts_result = text_to_speech(to_speak, "zh-TW")
        if tts_result:
            audio_bytes, mime = tts_result
            fname = save_tts_audio(audio_bytes, mime)
            duration = min(len(to_speak) * 300 + 1000, 60000)
            base_url = os.environ.get("RENDER_EXTERNAL_URL", "")
            if base_url:
                audio_url = f"{base_url}/tts/{fname}"
                reply_audio(reply_token, audio_url, duration)
            else:
                reply(reply_token, "🔊 需要設定 RENDER_EXTERNAL_URL 才能發送語音")
        else:
            reply(reply_token, "🔊 語音功能目前無法使用（RapidAPI 免費版不支援）")
        return True

    return False


def handle_ai_mention(reply_token: str, text: str):
    """@機器人 問問題"""
    m = re.match(r"^@?(?:機器人|家管|bot|助理|小花)\s+(.+)", text, re.IGNORECASE)
    if m:
        question = m.group(1).strip()
        answer = call_gemini(
            f"你是一個溫暖實用的家庭助理，用繁體中文回答，簡潔不囉嗦。\n\n問題：{question}"
        )
        reply(reply_token, answer)
        return True
    return False


def handle_admin(reply_token: str, event: MessageEvent, text: str):
    """管理指令"""
    if text in ["群組id", "群組ID", "groupid", "群id"]:
        source = event.source
        gid = getattr(source, "group_id", None) or getattr(source, "room_id", None) or "不是群組訊息"
        reply(reply_token, f"群組 ID：{gid}")
        return True

    m = re.match(r"^(?:我是|叫我|我叫)\s*(.+)", text)
    if m:
        name = m.group(1).strip()
        user_id = getattr(event.source, "user_id", "")
        approved = get_members()
        if name not in approved:
            names_str = "、".join(approved) if approved else "（尚未設定成員）"
            reply(reply_token, f"「{name}」不在成員名單裡喔！\n"
                               f"目前成員：{names_str}\n"
                               f"請用正確的家人稱呼 😊")
            return True
        if user_id and name:
            bg(register_member, user_id, name)
            _member_cache[user_id] = name
            reply(reply_token, f"好的！以後叫你「{name}」😊\n"
                               f"完成家事時傳「完成 家事名稱」就會記在你名下囉")
        return True

    return False


def handle_batch_log(reply_token: str, member: str, text: str) -> bool:
    """批量登錄：第一行「完成」，後續每行一個家事"""
    lines = [l.strip() for l in text.strip().splitlines()]
    if len(lines) < 2:
        return False

    first = lines[0]
    if first not in ["完成", "完成了"] and not re.match(r'^\d+[/／]\d+\s*完成', first):
        return False

    chore_lines = lines[1:]

    # 最後一行只有匹配到已登記成員才視為名字
    members_list = get_members()
    who = member or ""
    last = chore_lines[-1] if chore_lines else ""
    if last and not re.search(r'\d', last):
        matched = next((m for m in members_list if m in last or last in m), None)
        if matched:
            who = matched
            chore_lines = chore_lines[:-1]

    # 解析家事行
    chore_pattern = re.compile(r'^(.+?)(\d+\.?\d*)$')
    chores_sheet = None
    chores: list[tuple[str, float]] = []
    for line in chore_lines:
        if not line:
            continue
        m = chore_pattern.match(line)
        if m:
            chores.append((m.group(1).strip(), float(m.group(2))))
        else:
            if chores_sheet is None:
                chores_sheet = get_chores()
            matched_chore = next(
                (c for c in chores_sheet if line in c["name"] or c["name"] in line),
                None,
            )
            pts = matched_chore["points"] if matched_chore else 1.0
            name = matched_chore["name"] if matched_chore else line
            chores.append((name, pts))

    if not chores:
        reply(reply_token, "沒有找到任何家事，請確認格式：\n完成\n家事名稱\n家事名稱")
        return True

    # 上限檢查（跳過超過上限的項目）
    who = who or member or "家人"
    valid_chores: list[tuple[str, float]] = []
    capped_names: list[str] = []
    for name, pts in chores:
        cap = WEEKLY_CAPS.get(name)
        if cap is not None:
            already = get_member_weekly_chore_points(who, name)
            remaining = cap - already
            if remaining <= 0:
                capped_names.append(name)
                continue
            pts = min(pts, remaining)
        valid_chores.append((name, pts))

    if not valid_chores:
        cap_str = "、".join(capped_names)
        reply(reply_token, f"⚠️ {who} 本週「{cap_str}」已達點數上限，沒有新增記錄。")
        return True

    try:
        batch_log_points(who, valid_chores)
        summary = format_weekly_summary()
    except Exception as e:
        reply(reply_token, f"記錄失敗：{e}")
        return True

    total = sum(p for _, p in valid_chores)
    total_str = f"{total:.2f}".rstrip('0').rstrip('.')
    lines_out = [f"✅ {name} +{f'{pts:.2f}'.rstrip('0').rstrip('.')}" for name, pts in valid_chores]

    msg = f"📋 {who} 的家事記錄\n" + "\n".join(lines_out) + f"\n\n共 +{total_str} 點 🎉"
    if capped_names:
        msg += f"\n⚠️ 已達上限略過：{'、'.join(capped_names)}"
    msg += f"\n\n{summary}"
    reply(reply_token, msg)
    return True


def handle_help(reply_token: str, text: str):
    if text in ["說明", "幫助", "功能", "help", "指令", "指令清單", "清單"]:
        reply(reply_token, """🏠 家管助理指令清單

【家事】
• 完成 [家事名稱]
• 完成（換行列多項家事）— 批量記錄
• 家事清單 — 查所有家事
• 新增家事 [名稱] [點數]

【點數】
• 查點數 — 全員本週排行
• 我的點數 — 自己本週明細
• 取消記錄 [家事名稱] — 取消最近一筆

【購物】
• 買 [項目] — 加入購物清單
• 買好了 [項目] — 標記已購
• 購物清單 — 查看清單

【記帳】
• 記帳 [金額] [說明] — 記錄支出
• 今日帳 / 查帳 — 查今日/7天支出

【罰款】
• 繳罰款 [金額] — 投幣後登記
• 欠款 / 小本本 — 查累積欠款

【斷捨離】
• 斷捨離 [物品] — 加入待定區
• 丟了 [物品] — 標記丟棄
• 賣了 [物品] [金額] — 賣出並記帳
• 斷捨離清單 — 查待定區
• 斷捨離收入 — 查賣出總收入

【生活小工具】
• 天氣 — 今日天氣 + 空氣品質
• [日期]天氣 / [日期]會下雨嗎 — 支援「今天/明天/後天/星期三/下週五」等
• 今天吃什麼 — 隨機世界料理食譜
• [星座]運勢 — 例：天蠍座運勢
• 今日全員運勢 — 全家人運勢一次看
• 出題 — 家庭問答遊戲（答 xxx 作答）
• 笑話 / 說個笑話 / Chuck Norris
• 推薦飲料 [名稱] — 飲料食譜
• 今天做什麼 — 隨機休閒活動
• 今天運動 — 隨機運動建議
• 動漫名言 / 電影台詞 / 激勵名言
• 小花畫 [描述] — AI 生成圖片
• 匯率 [幣別] — 例：匯率 美金
• 金價 — 今日黃金價格
• 推薦電影 / 電影 [片名]
• 哪裡看 [片名] — 查串流平台
• BMI [身高] [體重] — 例：BMI 165 55
• 食譜 [食材] — 依食材找食譜
• 熱量 [食物] / 消耗熱量 [活動] [分鐘]
• 冷知識 / 天文冷知識 / 數字冷知識
• 今日宇宙 / NASA — 每日天文圖片
• 給我建議

【語言學習】
• 日文 [單字] — 查讀音 + 意思 + JLPT
• 今日日文單字 — 隨機 N5 單字
• 漢字 [字] — 查漢字讀音筆畫
• 今日漢字 — 隨機漢字 + 例句
• 西文 [單字] — 查西班牙文
• 今日西文單字 — 隨機西班牙文

【其他】
• 我是 [名字] — 登記身分
• 助理 [問題] / 小花 [問題] — AI 問答

目標：每週 5 點，少一點罰 50 元 🎯""")
        return True
    return False

# ─── Webhook 入口 ─────────────────────────────

@app.route("/")
def health():
    return "OK", 200


@app.route("/daily_push", methods=["POST"])
def daily_push():
    """早安推播（含 TTS），由 GitHub Actions 每天呼叫"""
    token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    if token != _token:  # 用現有的 LINE_CHANNEL_ACCESS_TOKEN 驗證
        abort(403)

    from sheets import get_members, get_chores, get_weekly_points
    from api_helpers import format_weather_block

    group_id = os.environ.get("LINE_GROUP_ID", "")
    if not group_id:
        return "LINE_GROUP_ID not set", 500

    def _push(messages: list):
        requests.post(
            "https://api.line.me/v2/bot/message/push",
            headers={"Authorization": f"Bearer {_token}", "Content-Type": "application/json"},
            json={"to": group_id, "messages": messages},
            timeout=10,
        )

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=3) as ex:
        f_members = ex.submit(get_members)
        f_pts     = ex.submit(get_weekly_points)
        f_chores  = ex.submit(get_chores)
        members = f_members.result()
        pts     = f_pts.result()
        chores  = f_chores.result()
    low_pts = [m for m in members if pts.get(m, 0) < POINTS_THRESHOLD]

    lines = ["☀️ 早安！家管助理日報\n"]
    lines.append(format_weather_block())
    lines.append("")
    if chores:
        lines.append(f"📋 今日待完成家事（共 {len(chores)} 項）：")
        for c in chores[:8]:
            lines.append(f"  • {c['name']}（{c['points']}點）")
    else:
        lines.append("🎉 今日家事全部完成！大家辛苦了！")
    lines.append("")
    if low_pts:
        lines.append("⚠️ 本週點數還不夠的成員：")
        for m in low_pts:
            lines.append(f"  {m}：目前 {pts.get(m,0)} 點（目標 {POINTS_THRESHOLD} 點）")
        lines.append("\n快去完成家事累積點數吧！💪")
    else:
        lines.append("✅ 大家本週點數都達標了，棒棒！🎉")
    lines.append("\n輸入「家事清單」查看待完成家事")
    text_body = "\n".join(lines)

    # 先送文字
    _push([{"type": "text", "text": text_body[:4900]}])

    # 再送 TTS 語音（早安問候）
    base_url = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
    if base_url:
        greeting = f"早安！今天天氣{'不錯，出門記得防曬！' if '晴' in text_body else '要注意，出門帶傘喔！'}"
        tts_result = text_to_speech(greeting, "zh-TW")
        if tts_result:
            audio_bytes, mime = tts_result
            fname = save_tts_audio(audio_bytes, mime)
            audio_url = f"{base_url}/tts/{fname}"
            duration = min(len(greeting) * 300 + 1000, 30000)
            _push([{"type": "audio", "originalContentUrl": audio_url, "duration": duration}])

    return "OK"


@app.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

def _process_text_message(reply_token: str, text: str, source, member: str = ""):
    """處理文字訊息的核心邏輯（文字/語音轉文字共用）"""
    if (
        handle_admin(reply_token, source, text) or
        handle_batch_log(reply_token, member, text) or
        handle_help(reply_token, text) or
        handle_chores(reply_token, member, text) or
        handle_points(reply_token, member, text) or
        handle_shopping(reply_token, member, text) or
        handle_accounting(reply_token, member, text) or
        handle_fine(reply_token, member, text) or
        handle_declutter(reply_token, member, text) or
        handle_fun(reply_token, source, text) or
        handle_ai_mention(reply_token, text)
    ):
        return

    # 被 @ 提及時 AI 回答
    if hasattr(source, "mention") and source.mention:
        answer = call_gemini(
            f"你是一個溫暖實用的家庭助理，用繁體中文回答，簡潔不囉嗦。\n\n問題：{text}"
        )
        reply(reply_token, answer)
        return

    # 拼字容錯：短指令找最接近的
    _KNOWN_COMMANDS = [
        "家事清單", "點數", "我的點數", "購物清單", "帳目", "欠款",
        "天氣", "今天吃什麼", "星座", "今日全員運勢", "笑話", "冷知識",
        "今日宇宙", "推薦電影", "新聞", "今日新聞", "金價", "激勵名言",
        "今日日文單字", "今日西文單字", "今日漢字", "說明", "指令清單",
        "今天做什麼", "今天運動", "動漫名言", "出題", "翻譯",
    ]
    if len(text) <= 8 and not re.search(r"[a-zA-Z0-9]", text):
        close = difflib.get_close_matches(text, _KNOWN_COMMANDS, n=1, cutoff=0.6)
        if close:
            reply(reply_token, f"你是想說「{close[0]}」嗎？試試傳那個指令 😊")


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event: MessageEvent):
    if not hasattr(event, "reply_token") or not event.reply_token:
        return

    text = event.message.text.strip()
    reply_token = event.reply_token

    member = ""
    if hasattr(event, "source") and hasattr(event.source, "user_id"):
        member = _resolve_member(event.source.user_id)

    _process_text_message(reply_token, text, event.source, member)


# ── 語音訊息處理（Speech-to-Text）────────────────

@handler.add(MessageEvent, message=AudioMessageContent)
def handle_audio_message(event: MessageEvent):
    """接收語音訊息，下載音檔後用 Gemini 轉文字，再當作文本處理"""
    if not hasattr(event, "reply_token") or not event.reply_token:
        return

    reply_token = event.reply_token
    audio = event.message

    # 取得音檔 URL
    audio_url = None
    if hasattr(audio, "content_provider") and audio.content_provider:
        cp = audio.content_provider
        if hasattr(cp, "original_content_url") and cp.original_content_url:
            audio_url = cp.original_content_url
        elif hasattr(cp, "content_url") and cp.content_url:
            audio_url = cp.content_url

    if not audio_url:
        reply(reply_token, "🎤 無法取得語音檔案，請確認設定")
        return

    # 下載音檔
    try:
        r = requests.get(audio_url, timeout=15)
        r.raise_for_status()
        audio_bytes = r.content
    except Exception as e:
        reply(reply_token, f"🎤 語音下載失敗：{e}")
        return

    # ── 語音轉文字：Groq Whisper 優先，Gemini 作 fallback ──
    transcript = groq_stt(audio_bytes, "audio/mpeg")

    if not transcript and GEMINI_KEY:
        try:
            import base64
            audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
            url = (
                "https://generativelanguage.googleapis.com/v1beta/"
                f"models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
            )
            payload = {
                "contents": [{
                    "parts": [
                        {"text": "請把這段語音轉成文字，只給轉錄結果，不要任何解釋。如果是中文請用繁體中文。"},
                        {"inline_data": {"mime_type": "audio/mpeg", "data": audio_b64}},
                    ]
                }]
            }
            resp = requests.post(url, json=payload, timeout=30)
            transcript = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        except Exception as e:
            reply(reply_token, f"🎤 語音轉文字失敗：{e}")
            return

    if not transcript:
        reply(reply_token, "🎤 語音轉文字無法使用，請設定 GROQ_API_KEY 或 GEMINI_API_KEY")
        return

    if not transcript:
        reply(reply_token, "🎤 聽不清楚，請再說一次")
        return

    # 告訴使用者聽到了什麼
    reply(reply_token, f"🎤 聽到：「{transcript[:80]}{'...' if len(transcript) > 80 else ''}」")

    # 繼續當作文本處理
    member = ""
    if hasattr(event, "source") and hasattr(event.source, "user_id"):
        member = _resolve_member(event.source.user_id)

    _process_text_message(reply_token, transcript, event.source, member)


# user_id → 成員名對照
_member_cache: dict[str, str] = {}
_cache_ts: float = 0

def _resolve_member(user_id: str) -> str:
    import time
    global _cache_ts
    now = time.time()
    if now - _cache_ts > 600:
        _refresh_member_cache()
        _cache_ts = now
    return _member_cache.get(user_id, "")

def _refresh_member_cache():
    try:
        from sheets import _read
        rows = _read("設定", "A2:B30")
        for r in rows:
            if len(r) >= 2 and r[0].strip() and r[1].strip():
                _member_cache[r[1].strip()] = r[0].strip()
    except Exception:
        pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
