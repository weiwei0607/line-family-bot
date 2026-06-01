"""
Daily Dose API — 為 Daily Dose App 提供內容 API
掛載在現有的 Flask app 上
"""

import logging
from flask import Blueprint, jsonify, request
from api_helpers import (
    get_motivation_quote, get_joke, get_fun_fact, get_astronomy_fact,
    get_exercise, get_anime_quote, get_horoscope, get_movie, get_tmdb_movie,
    get_random_activity, get_cocktail, get_meal_random, get_open_trivia,
    get_advice, get_movie_quote, get_chuck_norris, get_number_fact,
    get_nasa_apod, translate_text, SIGN_MAP,
)

dose_bp = Blueprint("dose", __name__, url_prefix="/dose")


def _json(data: dict | None):
    """包裝 JSON 回應，加上 CORS"""
    resp = jsonify(data or {"error": "未取得資料"})
    resp.headers.add("Access-Control-Allow-Origin", "*")
    resp.headers.add("Access-Control-Allow-Headers", "Content-Type,Authorization")
    resp.headers.add("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
    return resp


@dose_bp.route("/quote", methods=["GET"])
def dose_quote():
    q = get_motivation_quote()
    return _json(q)


@dose_bp.route("/joke", methods=["GET"])
def dose_joke():
    j = get_joke()
    return _json({"joke": j})


@dose_bp.route("/fact", methods=["GET"])
def dose_fact():
    f = get_fun_fact()
    return _json({"fact": f})


@dose_bp.route("/astronomy", methods=["GET"])
def dose_astronomy():
    f = get_astronomy_fact()
    return _json({"fact": f})


@dose_bp.route("/exercise", methods=["GET"])
def dose_exercise():
    e = get_exercise()
    return _json(e)


@dose_bp.route("/anime", methods=["GET"])
def dose_anime():
    q = get_anime_quote()
    return _json(q)


@dose_bp.route("/horoscope/<sign>", methods=["GET"])
def dose_horoscope(sign: str):
    # 支援中文或英文星座名
    sign = sign.strip()
    if sign in SIGN_MAP:
        # 傳入的是中文
        h = get_horoscope(sign)
    else:
        # 傳入的可能是英文，反向查找中文名
        _SIGN_REVERSE = {v: k for k, v in SIGN_MAP.items()}
        sign_zh = _SIGN_REVERSE.get(sign.lower())
        h = get_horoscope(sign_zh) if sign_zh else None
    return _json(h)


@dose_bp.route("/movie", methods=["GET"])
def dose_movie():
    m = get_tmdb_movie() or get_movie()
    return _json(m)


@dose_bp.route("/apod", methods=["GET"])
def dose_apod():
    return _json(get_nasa_apod())


@dose_bp.route("/activity", methods=["GET"])
def dose_activity():
    a = get_random_activity()
    return _json(a)


@dose_bp.route("/cocktail", methods=["GET"])
def dose_cocktail():
    # 隨機推薦，不指定名稱
    c = get_cocktail("")
    return _json(c)


@dose_bp.route("/meal", methods=["GET"])
def dose_meal():
    m = get_meal_random()
    return _json(m)


@dose_bp.route("/trivia", methods=["GET"])
def dose_trivia():
    t = get_open_trivia()
    return _json(t)


@dose_bp.route("/advice", methods=["GET"])
def dose_advice():
    a = get_advice()
    return _json({"advice": a})


@dose_bp.route("/movie_quote", methods=["GET"])
def dose_movie_quote():
    q = get_movie_quote()
    return _json(q)


@dose_bp.route("/chuck_norris", methods=["GET"])
def dose_chuck():
    j = get_chuck_norris()
    return _json({"joke": j})


@dose_bp.route("/number", methods=["GET"])
def dose_number():
    n = get_number_fact()
    return _json({"fact": n})


@dose_bp.route("/translate", methods=["POST"])
def dose_translate():
    data = request.get_json() or {}
    text = data.get("text", "")
    target = data.get("target", "zh-TW")
    if not text:
        return _json({"error": "請提供 text 欄位"})
    result = translate_text(text, target)
    return _json({"original": text, "translated": result, "target": target})


@dose_bp.route("/all", methods=["GET"])
def dose_all():
    """一次取得所有 Daily Dose 內容（給首頁用）—— 並行呼叫所有外部 API"""
    import random
    from concurrent.futures import ThreadPoolExecutor, as_completed

    sign_zh = random.choice(list(SIGN_MAP.keys()))

    _FETCHERS = {
        "quote": get_motivation_quote,
        "joke": get_joke,
        "fact": get_fun_fact,
        "astronomy": get_astronomy_fact,
        "exercise": get_exercise,
        "anime": get_anime_quote,
        "horoscope": lambda: get_horoscope(SIGN_MAP[sign_zh]),
        "movie": get_movie,
        "activity": get_random_activity,
        "cocktail": lambda: get_cocktail(""),
        "meal": get_meal_random,
        "advice": get_advice,
    }

    results: dict[str, any] = {"horoscope_sign": sign_zh}
    with ThreadPoolExecutor(max_workers=6) as pool:
        future_to_key = {
            pool.submit(fn): key for key, fn in _FETCHERS.items()
        }
        for future in as_completed(future_to_key):
            key = future_to_key[future]
            try:
                results[key] = future.result(timeout=15)
            except Exception as exc:
                logging.warning("dose_all %s failed: %s", key, exc)
                results[key] = None

    return _json(results)
