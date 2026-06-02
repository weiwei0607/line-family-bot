"""
Family bot language handlers.
Japanese lookup, Spanish lookup, translation.
"""

import re
from language_api import get_jisho, get_kanji_info, get_spanish_dict
from api_helpers import translate_text, smart_translate, call_ai
from line_push import reply_text as reply


# Language alias mappings
_LANG_ALIASES = {
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

_LANG_DISPLAY = {
    "zh-TW": "繁體中文", "zh-CN": "簡體中文", "en": "英文",
    "ja": "日文", "ko": "韓文", "es": "西班牙文", "fr": "法文",
    "de": "德文", "th": "泰文", "vi": "越南文", "id": "印尼文",
}


def _handle_language(reply_token: str, text: str) -> bool:
    """
    Handle language-related commands: Japanese, Spanish, translation.
    Returns True if handled.
    """
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
            reply(reply_token, call_ai(f"用繁體中文解釋日文單字「{word}」的意思和讀音"))
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
            reply(reply_token, call_ai(f"用繁體中文解釋日文漢字「{char}」的讀音和意思"))
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
            reply(reply_token, call_ai(
                f"用繁體中文解釋西班牙文單字「{word}」的意思、詞性和一個例句"
            ))
        return True

    # ── 翻譯 ──
    m = re.match(r"^(?:翻譯|翻|translate)\s*(?:成?([\w\-]+)\s+)?(.+)", text, re.IGNORECASE)
    if m and m.group(2):
        target = (m.group(1) or "zh-TW").strip().lower()
        to_translate = m.group(2).strip()
        target = _LANG_ALIASES.get(target, target)
        lang_display = _LANG_DISPLAY.get(target, target)
        result = translate_text(to_translate, target)
        reply(reply_token, f"🌐 {lang_display}翻譯：\n\n{result}")
        return True

    if text in ["翻譯", "translate"]:
        reply(reply_token, "請傳「翻譯 [文字]」或「翻譯成英文 [文字]」\n例：翻譯成日文 你好")
        return True

    return False
