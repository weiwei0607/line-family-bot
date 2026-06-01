

"""Language Api for line-family-bot."""

import requests
import os
from datetime import datetime, timedelta
import random
import logging
__all__ = ['JLPT_N5_KANJI', 'JLPT_N5_WORDS', 'get_jisho', 'get_kanji_info', 'get_random_jlpt_word', 'get_spanish_dict', 'logger']


logger = logging.getLogger(__name__)

from api_helpers import (
_retry_http, call_gemini
)


JLPT_N5_KANJI = [
    "日", "月", "火", "水", "木", "金", "土", "山", "川", "田",
    "人", "口", "目", "耳", "手", "足", "上", "下", "中", "大",
    "小", "一", "二", "三", "四", "五", "六", "七", "八", "九",
    "十", "百", "千", "年", "時", "間", "学", "校", "先", "生",
    "友", "家", "会", "社", "車", "電", "駅", "道", "食", "飲",
    "見", "聞", "話", "読", "書", "来", "行", "国", "語", "本",
    "花", "犬", "猫", "魚", "鳥", "空", "海", "雨", "雪", "風",
]

JLPT_N5_WORDS = [
    "食べる", "飲む", "行く", "来る", "見る", "聞く", "話す", "読む", "書く", "買う",
    "起きる", "寝る", "食べ物", "飲み物", "学校", "電車", "友達", "家族", "先生",
    "毎日", "今日", "明日", "昨日", "今年", "来年", "去年", "時間", "場所",
    "日本語", "英語", "中国語", "言葉", "勉強", "仕事", "休み", "旅行",
    "電話", "新聞", "雑誌", "料理", "音楽", "映画", "写真", "天気",
]


def get_jisho(word: str) -> dict | None:
    try:
        r = requests.get(
            "https://jisho.org/api/v1/search/words",
            params={"keyword": word},
            timeout=10,
        )
        data = r.json().get("data", [])
        if not data:
            return None
        entry = data[0]
        readings = entry.get("japanese", [{}])
        senses = entry.get("senses", [{}])
        meanings_en = []
        for s in senses[:3]:
            meanings_en.extend(s.get("english_definitions", [])[:2])
        return {
            "word": readings[0].get("word") or readings[0].get("reading", word),
            "reading": readings[0].get("reading", ""),
            "meanings_en": meanings_en[:4],
            "jlpt": entry.get("jlpt", []),
            "common": entry.get("is_common", False),
        }
    except Exception:
        return None


def get_kanji_info(char: str) -> dict | None:
    # SSRF guard: only allow a single CJK character or simple ASCII
    if not char or len(char) > 1 or (ord(char) < 0x4E00 and not char.isascii()):
        return None
    try:
        r = requests.get(f"https://kanjiapi.dev/v1/kanji/{char}", timeout=8)
        if r.status_code != 200:
            return None
        d = r.json()
        return {
            "kanji": d.get("kanji", ""),
            "meanings": d.get("meanings", [])[:4],
            "kun_readings": d.get("kun_readings", [])[:3],
            "on_readings": d.get("on_readings", [])[:3],
            "jlpt": d.get("jlpt"),
            "stroke_count": d.get("stroke_count"),
        }
    except Exception:
        return None


def get_random_jlpt_word() -> dict | None:
    word = random.choice(JLPT_N5_WORDS)
    return get_jisho(word)

def get_spanish_dict(word: str) -> dict | None:
    try:
        r = requests.get(
            f"https://api.dictionaryapi.dev/api/v2/entries/es/{word}",
            timeout=8,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        if not data or isinstance(data, dict):
            return None
        entry = data[0]
        meanings = entry.get("meanings", [])
        definitions = []
        for m in meanings[:2]:
            for d in m.get("definitions", [])[:2]:
                df = d.get("definition", "")
                if df:
                    definitions.append(df)
        return {
            "word": entry.get("word", word),
            "phonetic": entry.get("phonetic", ""),
            "definitions": definitions[:3],
        }
    except Exception:
        return None
