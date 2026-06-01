"""
Family bot image handlers.
AI image generation, photo search, GIFs, animals, QR codes.
"""

import re
from api_helpers import (
    generate_image, search_photo, get_curated_photo,
    search_gif, get_trending_gif,
    get_cat_image, get_dog_image, make_qr_url,
)
from line_push import reply_text as reply, reply_image, reply_image_with_text


def _handle_images(reply_token: str, text: str) -> bool:
    """
    Handle image-related commands: AI draw, photo search, GIF, animals, QR.
    Returns True if handled.
    """
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

    # ── 找圖（Pexels）──
    m = re.match(r"^找圖\s+(.+)$", text)
    if m:
        query = m.group(1).strip()
        url = search_photo(query)
        if url:
            reply_image(reply_token, url)
        else:
            reply(reply_token, f"找不到「{query}」的圖片，試試其他關鍵字")
        return True

    if text in ["隨機圖片", "來張圖"]:
        url = get_curated_photo()
        if url:
            reply_image(reply_token, url)
        else:
            reply(reply_token, "圖片載入失敗，待會再試")
        return True

    # ── GIF 搜尋（GIPHY）──
    m = re.match(r"^(?:GIF|gif|找GIF|動圖)\s+(.+)$", text, re.IGNORECASE)
    if m:
        query = m.group(1).strip()
        result = search_gif(query)
        if result and result.get("gif_url"):
            reply_image_with_text(reply_token, result["still_url"] or result["gif_url"], result["gif_url"])
        else:
            reply(reply_token, f"找不到「{query}」的 GIF，試試其他關鍵字")
        return True

    if text in ["熱門GIF", "隨機GIF", "來個動圖"]:
        result = get_trending_gif()
        if result and result.get("gif_url"):
            reply_image_with_text(reply_token, result["still_url"] or result["gif_url"], result["gif_url"])
        else:
            reply(reply_token, "GIF 載入失敗，待會再試")
        return True

    # ── 貓咪 / 狗狗圖片 ──
    if text in ["貓咪圖", "貓貓", "來隻貓", "貓圖", "🐱"]:
        url = get_cat_image()
        if url:
            reply_image(reply_token, url)
        else:
            reply(reply_token, "貓咪暫時跑走了，待會再試 🐱")
        return True

    if text in ["柴柴", "來隻柴柴", "柴犬圖", "柴犬"]:
        url = get_dog_image("shiba")
        if url:
            reply_image(reply_token, url)
        else:
            reply(reply_token, "柴柴暫時跑走了，待會再試 🐕")
        return True

    if text in ["狗狗圖", "狗狗", "來隻狗", "狗圖", "🐶"]:
        url = get_dog_image()
        if url:
            reply_image(reply_token, url)
        else:
            reply(reply_token, "狗狗暫時跑走了，待會再試 🐶")
        return True

    # ── QR Code ──
    m = re.match(r"^(?:QR|qr|QR碼|二維碼)\s+(.+)$", text, re.IGNORECASE)
    if m:
        qr_url = make_qr_url(m.group(1).strip())
        reply_image(reply_token, qr_url)
        return True

    return False
