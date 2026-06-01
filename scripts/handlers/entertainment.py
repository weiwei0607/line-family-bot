"""
Family bot entertainment handlers.
Drinks, movies, NASA APOD.
"""

import re
from api_helpers import (
    get_cocktail, get_movie, get_streaming, get_nasa_apod,
    smart_translate, call_gemini, QUOTA_MSG,
)
from line_push import reply_text as reply, reply_image_with_text


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


def _check_quota(result, reply_token: str) -> bool:
    """Check if result is a quota-exceeded message."""
    if isinstance(result, dict) and result.get("_quota"):
        reply(reply_token, QUOTA_MSG)
        return True
    return False


def _handle_entertainment(reply_token: str, text: str) -> bool:
    """
    Handle entertainment commands: drinks, movies, NASA APOD.
    Returns True if handled.
    """
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

    # ── 電影 ──
    if text in ["推薦電影", "今晚看什麼", "電影推薦", "看電影"]:
        movie = get_movie()
        if _check_quota(movie, reply_token):
            return True
        if movie:
            _send_movie(reply_token, movie)
        else:
            reply(reply_token, call_gemini("推薦一部適合全家看的電影，給出片名、年份、一句理由"))
        return True

    m = re.match(r"^電影\s+(.+)$", text)
    if m:
        title = m.group(1).strip()
        movie = get_movie(title)
        if _check_quota(movie, reply_token):
            return True
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
        if _check_quota(opts, reply_token):
            return True
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

    # ── NASA 每日天文圖 ──
    if text in ["今日宇宙", "宇宙圖片", "NASA", "天文圖", "宇宙"]:
        apod = get_nasa_apod()
        if _check_quota(apod, reply_token):
            return True
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

    return False
