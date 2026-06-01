"""
Family bot TTS (text-to-speech) handler.
"""

import re
import os
from api_helpers import text_to_speech, save_tts_audio
from line_push import reply_text as reply, reply_audio


def _handle_tts(reply_token: str, text: str) -> bool:
    """
    Handle TTS commands: '念/唸/說/讀 [text]'.
    Returns True if handled.
    """
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
