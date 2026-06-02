"""
Family bot tidy-log handlers.
Record and view tidy/cleaning logs.
"""

import re
import logging
from linebot.v3.messaging import ApiClient, MessagingApi
from sheets import add_tidy_log, format_tidy_summary, _detect_area
from line_push import reply_text as reply

logger = logging.getLogger(__name__)

def _handle_tidy(reply_token: str, text: str, member: str, source, configuration) -> bool:
    """
    Handle tidy/cleaning log commands.
    source: LINE message source object (for fetching profile if member unknown)
    Returns True if handled.
    """
    if text in ["收拾", "整理"]:
        try:
            reply(reply_token, format_tidy_summary())
        except Exception as exc:
            logger.exception("format_tidy_summary failed: %s", exc)
            reply(reply_token, f"❌ 讀取收拾紀錄失敗：{type(exc).__name__}")
        return True

    m_tidy = re.match(r"^(收拾|整理)\s*(.+)", text)
    if m_tidy:
        content = m_tidy.group(2).strip()
        # 嘗試解析區域
        area = _detect_area(content)
        # 如果沒偵測到區域，看文字開頭是否標註
        if area == "未分類":
            if content.startswith("自己 ") or content.startswith("我的 "):
                area = "自己"
                content = content[3:].strip()
            elif content.startswith("公共 ") or content.startswith("公用 "):
                area = "公共"
                content = content[3:].strip()
        # 優先使用已解析的 member（限定有效成員），沒有再嘗試抓 LINE profile
        _VALID_MEMBERS = {"爸爸", "媽媽", "姊姊", "妹妹"}
        if not member or member not in _VALID_MEMBERS:
            try:
                with ApiClient(configuration) as api_client:
                    profile = MessagingApi(api_client).get_profile(getattr(source, "user_id", ""))
                    member = profile.display_name
            except Exception as _exc:
                logger.warning("Silent error: %s", _exc)
        if not member or member not in _VALID_MEMBERS:
            member = "家人"
        try:
            add_tidy_log(member, area, content)
            area_emoji = "🏠" if area == "自己" else "🛋" if area == "公共" else "📦"
            reply(reply_token, f"✅ 已記錄！\n{area_emoji} {member} → {content}（{area}區域）\n\n傳「收拾」查看今天全家紀錄")
        except Exception as exc:
            logger.exception("add_tidy_log failed: %s", exc)
            reply(reply_token, f"❌ 記錄收拾失敗：{type(exc).__name__}，請稍後再試")
        return True

    return False
