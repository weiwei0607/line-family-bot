"""
Shared LINE push/reply helpers (used by both group-bot and family-bot).
"""

import os
import logging
import requests
import time
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, TextMessage, ImageMessage, AudioMessage,
)

logger = logging.getLogger(__name__)

_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
_LINE_GROUP_ID = os.environ.get("LINE_GROUP_ID", "")

_configuration = None


def _alert_admin(msg: str) -> None:
    """Notify admin via Telegram (best-effort)."""
    try:
        from shared.alerts import send_telegram_alert
        send_telegram_alert(msg, prefix="🏠 家管助理 Alert")
    except Exception:
        pass


def _get_configuration():
    global _configuration
    if _configuration is None:
        _configuration = Configuration(access_token=_CHANNEL_ACCESS_TOKEN)
    return _configuration


def _reply_messages(reply_token: str, messages: list):
    """Use requests directly to avoid urllib3 hanging issues in LINE Bot SDK."""
    if not reply_token or not messages:
        return
    try:
        resp = _retry_http(
            lambda: requests.post(
                "https://api.line.me/v2/bot/message/reply",
                headers={
                    "Authorization": f"Bearer {_CHANNEL_ACCESS_TOKEN}",
                    "Content-Type": "application/json",
                },
                json={"replyToken": reply_token, "messages": messages},
                timeout=15,
            )
        )
        logger.info("LINE reply status=%s len=%s", resp.status_code, len(str(messages)))
    except Exception as exc:
        logger.warning("_reply_messages failed: %s", exc)
        raise


def reply_text(reply_token: str, text: str):
    try:
        _reply_messages(reply_token, [{"type": "text", "text": text[:4900]}])
    except Exception as exc:
        logger.warning("reply_text failed (falling back to push): %s", exc)
        if _LINE_GROUP_ID:
            try:
                push_text(_LINE_GROUP_ID, text)
            except Exception as push_exc:
                logger.error("reply+push both failed: %s", push_exc)
                _alert_admin(f"LINE reply+push 皆失敗: {push_exc}\n原文: {text[:100]}")
        else:
            logger.error("reply failed and no LINE_GROUP_ID for push fallback")
            _alert_admin(f"LINE reply 失敗且無 GROUP_ID: {exc}\n原文: {text[:100]}")


def reply_image(reply_token: str, image_url: str, fallback_text: str = "圖片發送失敗"):
    try:
        _reply_messages(reply_token, [{"type": "image", "originalContentUrl": image_url, "previewImageUrl": image_url}])
    except Exception as exc:
        logger.warning("reply_image failed: %s", exc)
        reply_text(reply_token, fallback_text)


def reply_audio(reply_token: str, audio_url: str, duration: int = 5000, fallback_text: str = "語音發送失敗"):
    try:
        _reply_messages(reply_token, [{"type": "audio", "originalContentUrl": audio_url, "duration": duration}])
    except Exception as exc:
        logger.warning("reply_audio failed: %s", exc)
        reply_text(reply_token, fallback_text)


def reply_image_with_text(reply_token: str, image_url: str, text: str):
    try:
        _reply_messages(reply_token, [
            {"type": "image", "originalContentUrl": image_url, "previewImageUrl": image_url},
            {"type": "text", "text": text[:4900]},
        ])
    except Exception as exc:
        logger.warning("reply_image_with_text failed (falling back to push): %s", exc)
        if _LINE_GROUP_ID:
            push_messages(_LINE_GROUP_ID, [{"type": "text", "text": text[:4900]}])
        else:
            reply_text(reply_token, text)


def _retry_http(fn, max_retries=3, backoff=2):
    last_exc = None
    for attempt in range(max_retries):
        try:
            return fn()
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                time.sleep(backoff ** attempt)
    raise last_exc


def push_messages(to: str, messages: list):
    if not to or not messages:
        return
    try:
        _retry_http(
            lambda: requests.post(
                "https://api.line.me/v2/bot/message/push",
                headers={
                    "Authorization": f"Bearer {_CHANNEL_ACCESS_TOKEN}",
                    "Content-Type": "application/json",
                },
                json={"to": to, "messages": messages},
                timeout=30,
            )
        )
    except Exception as exc:
        logger.warning("push_messages failed: %s", exc)
        _alert_admin(f"LINE push 失敗: {exc}")


def push_text(to: str, text: str):
    push_messages(to, [{"type": "text", "text": text}])


def push_text_to_group(text: str):
    """Push text to the default LINE_GROUP_ID."""
    if _LINE_GROUP_ID:
        push_text(_LINE_GROUP_ID, text)


def push_audio(to: str, audio_url: str, duration: int = 5000):
    push_messages(to, [{"type": "audio", "originalContentUrl": audio_url, "duration": duration}])
