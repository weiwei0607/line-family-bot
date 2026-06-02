"""
LINE Family Bot — Simple command dispatch table for handle_fun.
Extracts the most repetitive if-blocks that do a single API call + reply.
"""

import re
import logging
from api_helpers import (
    get_fun_fact, get_advice, get_motivation_quote, get_movie_quote,
    get_astronomy_fact, get_chuck_norris, get_number_fact, get_news_round_robin,
    get_random_jlpt_word, get_kanji_info, get_meal_random, get_random_activity,
    get_exercise, get_anime_quote, get_joke_round_robin,
    smart_translate, call_ai,
    JLPT_N5_KANJI, QUOTA_MSG,
)

logger = logging.getLogger(__name__)


_SIMPLE_TEXT_COMMANDS = {
    "今天吃什麼": ("_cmd_meal",),
    "吃什麼": ("_cmd_meal",),
    "晚餐吃什麼": ("_cmd_meal",),
    "午餐吃什麼": ("_cmd_meal",),
    "星座": ("_cmd_zodiac_help",),
    "出題": ("_cmd_trivia_help",),
    "來玩問答": ("_cmd_trivia_help",),
    "問答遊戲": ("_cmd_trivia_help",),
    "出一題": ("_cmd_trivia_help",),
    "笑話": ("_cmd_joke",),
    "說個笑話": ("_cmd_joke",),
    "講個笑話": ("_cmd_joke",),
    "今天做什麼": ("_cmd_activity",),
    "無聊": ("_cmd_activity",),
    "推薦活動": ("_cmd_activity",),
    "隨機活動": ("_cmd_activity",),
    "今天運動": ("_cmd_exercise",),
    "運動建議": ("_cmd_exercise",),
    "健身建議": ("_cmd_exercise",),
    "動漫名言": ("_cmd_anime_quote",),
    "動漫語錄": ("_cmd_anime_quote",),
    "今日動漫": ("_cmd_anime_quote",),
    "電影台詞": ("_cmd_movie_quote",),
    "名片台詞": ("_cmd_movie_quote",),
    "電影名言": ("_cmd_movie_quote",),
    "冷知識": ("_cmd_fun_fact",),
    "今日冷知識": ("_cmd_fun_fact",),
    "告訴我一件事": ("_cmd_fun_fact",),
    "給我建議": ("_cmd_advice",),
    "人生建議": ("_cmd_advice",),
    "今日建議": ("_cmd_advice",),
    "金玉良言": ("_cmd_advice",),
    "激勵名言": ("_cmd_motivation",),
    "給我力量": ("_cmd_motivation",),
    "今日名言": ("_cmd_motivation",),
    "名言": ("_cmd_motivation",),
    "天文冷知識": ("_cmd_astronomy",),
    "科學冷知識": ("_cmd_astronomy",),
    "宇宙冷知識": ("_cmd_astronomy",),
    "Chuck Norris": ("_cmd_chuck",),
    "查克諾里斯": ("_cmd_chuck",),
    "功夫笑話": ("_cmd_chuck",),
    "數字冷知識": ("_cmd_number_fact",),
    "數字趣聞": ("_cmd_number_fact",),
    "新聞": ("_cmd_news",),
    "今日新聞": ("_cmd_news",),
    "頭條": ("_cmd_news",),
    "今天新聞": ("_cmd_news",),
    "今日日文單字": ("_cmd_jlpt_word",),
    "日文單字": ("_cmd_jlpt_word",),
    "學日文": ("_cmd_jlpt_word",),
    "今日漢字": ("_cmd_kanji_daily",),
    "隨機漢字": ("_cmd_kanji_daily",),
    "學漢字": ("_cmd_kanji_daily",),
    "今日西文單字": ("_cmd_spanish_word",),
    "西文單字": ("_cmd_spanish_word",),
    "學西文": ("_cmd_spanish_word",),
    "學西班牙文": ("_cmd_spanish_word",),
}


# ─── Handlers ─────────────────────────────────────────────

def _cmd_meal(reply):
    meal = get_meal_random()
    if meal:
        name_zh = smart_translate(meal["name"])
        ingr = "、".join(meal["ingredients"][:6])
        ingr_zh = smart_translate(ingr)
        lines = [f"🍽 今天來做：{name_zh}（{meal['area']} 料理）\n", f"食材：{ingr_zh}"]
        if meal.get("youtube"):
            lines.append(f"\n▶️ 做法影片：{meal['youtube']}")
        reply("\n".join(lines))
    else:
        reply(call_ai(
            "隨機推薦一道台灣家常料理，格式：\n🍽 [菜名]\n食材：xxx\n做法：xxx（一句話）"
        ))


def _cmd_zodiac_help(reply):
    reply("請傳「[星座]運勢」\n例：天蠍座運勢、射手運勢")


def _cmd_trivia_help(reply):
    reply("傳「出題」開始問答遊戲！")


def _cmd_joke(reply):
    joke_en = get_joke_round_robin()
    if joke_en == QUOTA_MSG:
        reply(QUOTA_MSG)
        return
    if joke_en and any(ord(c) > 127 for c in joke_en[:20]):
        reply(f"😂 {joke_en}")
    elif joke_en:
        reply(f"😂 {smart_translate(joke_en)}")
    else:
        reply(call_ai("說一個適合全家的台灣笑話"))


def _cmd_activity(reply):
    data = get_random_activity()
    if data and data.get("activity"):
        reply(f"🎯 今天來試試：\n\n{smart_translate(data['activity'])}\n\n（適合 {data.get('participants','?')} 人）")
    else:
        reply(call_ai("推薦一個適合全家一起做的休閒活動，用繁體中文回答"))


_BODY_PART_ZH = {
    "back": "背部", "chest": "胸部", "lower arms": "前臂", "lower legs": "小腿",
    "neck": "頸部", "shoulders": "肩膀", "upper arms": "上臂", "upper legs": "大腿",
    "waist": "腰腹", "cardio": "有氧", "core": "核心",
}
_EQUIPMENT_ZH = {
    "barbell": "槓鈴", "dumbbell": "啞鈴", "body weight": "徒手", "cable": "拉力繩",
    "band": "彈力帶", "kettlebell": "壺鈴", "machine": "器械", "roller": "滾筒",
    "band-light": "輕彈力帶", "ez barbell": "曲柄槓鈴", "smith machine": "史密斯機",
    "resistance band": "彈力帶", "assisted": "輔助器械",
}

def _cmd_exercise(reply):
    data = get_exercise()
    if data:
        body = _BODY_PART_ZH.get(data.get("bodyPart", "").lower(), data.get("bodyPart", ""))
        equip = _EQUIPMENT_ZH.get(data.get("equipment", "").lower(), data.get("equipment", ""))
        reply(f"💪 今日運動：{smart_translate(data.get('name',''))}\n\n部位：{body}\n器材：{equip}")
    else:
        reply(call_ai("推薦一個適合在家做的簡單運動，說明動作和次數"))


def _cmd_anime_quote(reply):
    data = get_anime_quote()
    if data and data.get("quote"):
        reply(f"🌸 {smart_translate(data['quote'])}\n\n—《{data['anime']}》{data['character']}")
    else:
        reply(call_ai("給我一句著名動漫台詞，說出出自哪部作品"))


def _cmd_movie_quote(reply):
    q = get_movie_quote()
    if q and q.get("quote"):
        reply(f"🎬 「{q['quote']}」\n\n—《{q['movie']}》{q['character']}")
    else:
        reply(call_ai("給我一句著名電影的經典英文原句台詞，並標註電影中文名稱和角色名。格式：台詞（保留英文原句）\n—《電影中文名》角色名"))


def _cmd_fun_fact(reply):
    fact_en = get_fun_fact()
    if fact_en:
        reply(f"🤓 冷知識\n\n{smart_translate(fact_en)}")
    else:
        reply(call_ai("給我一個有趣的冷知識，用繁體中文"))


def _cmd_advice(reply):
    advice_en = get_advice()
    if advice_en:
        reply(f"💡 {smart_translate(advice_en)}\n\n（{advice_en}）")
    else:
        reply("今天沒有建議，就靠自己吧！")


def _cmd_motivation(reply):
    q = get_motivation_quote()
    if q and q.get("text"):
        reply(f"✨ {smart_translate(q['text'])}\n\n— {q['author']}")
    else:
        reply(call_ai("給我一句激勵人心的名言，用繁體中文"))


def _cmd_astronomy(reply):
    fact_en = get_astronomy_fact()
    if fact_en == QUOTA_MSG:
        reply(QUOTA_MSG)
        return
    if fact_en:
        reply(f"🔭 {smart_translate(fact_en)}")
    else:
        reply(call_ai("給我一個有趣的天文或科學冷知識，用繁體中文"))


def _cmd_chuck(reply):
    joke_en = get_chuck_norris()
    if joke_en:
        reply(f"💪 {smart_translate(joke_en)}")
    else:
        reply(call_ai("說一個關於超強壯男人的誇張笑話，用繁體中文"))


def _cmd_number_fact(reply):
    fact_en = get_number_fact()
    if fact_en:
        reply(f"🔢 {smart_translate(fact_en)}")
    else:
        reply(call_ai("給我一個關於數字的有趣冷知識，用繁體中文"))


def _cmd_news(reply):
    items = get_news_round_robin()
    if items == QUOTA_MSG:
        reply(QUOTA_MSG)
        return
    if items:
        lines = ["📰 今日頭條\n"]
        for i, it in enumerate(items[:5], 1):
            lines.append(f"{i}. {it.get('title', '')}")
        reply("\n".join(lines))
    else:
        reply("新聞取得失敗，待會再試")


def _cmd_jlpt_word(reply):
    data = get_random_jlpt_word()
    if data:
        jlpt = f"JLPT {data['jlpt'][0].upper()}" if data.get("jlpt") else "N5"
        meanings_zh = smart_translate(", ".join(data["meanings_en"]))
        reply(f"📖 今日日文單字（{jlpt}）\n\n✏️ {data['word']}　読み：{data['reading']}\n意思：{meanings_zh}\n\n試著造個句子看看！")
    else:
        reply(call_ai("給我一個 JLPT N5 等級的日文單字，包含：單字、假名讀音、繁體中文意思、一個例句"))


def _cmd_kanji_daily(reply):
    import random
    char = random.choice(JLPT_N5_KANJI)
    data = get_kanji_info(char)
    if data:
        jlpt = f"JLPT N{data['jlpt']}" if data.get("jlpt") else "N5"
        on = "、".join(data["on_readings"]) or "—"
        kun = "、".join(data["kun_readings"]) or "—"
        meanings = "、".join(data["meanings"]) or "—"
        example = call_ai(f"用「{char}」造一個簡單的日文例句，附上假名讀音和繁體中文翻譯")
        reply(f"🈶 今日漢字：{data['kanji']}（{jlpt}）\n\n音讀：{on}\n訓讀：{kun}\n意思：{meanings}\n筆畫：{data['stroke_count']}\n\n例句：\n{example}")
    else:
        reply(call_ai(f"用繁體中文介紹日文漢字「{char}」，包含讀音、意思和一個例句"))


def _cmd_spanish_word(reply):
    reply(call_ai(
        "給我一個 A1-A2 等級的西班牙文單字，格式：\n"
        "📖 單字：xxx\n"
        "詞性：xxx\n"
        "中文意思：xxx\n"
        "例句：xxx（附中文翻譯）\n"
        "記憶技巧：xxx（一句話）"
    ))


# ─── Public API ───────────────────────────────────────────

def try_dispatch(text: str, reply_fn) -> bool:
    """
    Try to dispatch a simple command.
    reply_fn is a callable that takes a single text argument.
    Returns True if dispatched, False otherwise.
    """
    handler_name = _SIMPLE_TEXT_COMMANDS.get(text)
    if handler_name:
        # handler_name is a tuple like ("_cmd_meal",)
        name = handler_name[0]
        func = globals()[name]
        func(reply_fn)
        return True
    return False
