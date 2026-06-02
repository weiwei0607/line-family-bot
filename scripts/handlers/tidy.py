"""
Family bot tidy-log handlers.
Record and view tidy/cleaning logs.
Also detects vacuum-robot maintenance keywords and logs them simultaneously.
"""

import os
import re
import logging
from linebot.v3.messaging import ApiClient, MessagingApi
from sheets import add_tidy_log, format_tidy_summary, _detect_area
from line_push import reply_text as reply

logger = logging.getLogger(__name__)

# 引用小白模組的關鍵字（避免重複定義）
_VACUUM_KEYWORDS = {
    "empty_dustbin":  ["倒集塵盒", "倒垃圾", "清集塵盒"],
    "clean_dustbin":  ["洗集塵盒", "洗塵盒",
                       "集塵盒清洗", "集塵盒清理", "塵盒清洗", "集塵盒清"],
    "clean_brush":    ["清理主刷", "清主刷", "洗主刷", "清理滾刷", "清滾刷",
                       "主刷清理", "滾刷清理", "主刷清洗", "滾刷清洗"],
    "replace_brush":  ["換主刷", "換滾刷", "主刷換新", "換新主刷",
                       "主刷更換", "滾刷更換"],
    "replace_filter": ["換濾網", "濾網換新", "換新濾網", "換hepa", "換HEPA",
                       "濾網更換", "HEPA更換", "hepa更換"],
}


def _match_vacuum_actions(line: str) -> list[str]:
    """掃描一行文字裡所有小白維護關鍵字，回傳 action 列表（可複數）"""
    t = line.replace(" ", "").replace("　", "")
    matched = []
    for action, keywords in _VACUUM_KEYWORDS.items():
        for kw in keywords:
            if kw in t:
                matched.append(action)
                break  # 該 action 已命中，下一個 action
    return matched


def _get_vacuum_reminders() -> str:
    """取得小白超期提醒簡訊，沒有則回傳空字串"""
    try:
        import sys
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from vacuum_tracker import _load_records, _days_since, SCHEDULE

        records = _load_records()
        alerts = []
        for action, s in SCHEDULE.items():
            relevant = [r for r in records if r["action"] == action]
            if relevant:
                latest = max(relevant, key=lambda r: r["timestamp"])
                days = _days_since(latest["timestamp"])
                if days > s["days"]:
                    alerts.append(f"{s['icon']} {s['label']} 已過 {days} 天（建議每{s['days']}天）")
        if alerts:
            return "\n".join(alerts)
    except Exception as exc:
        logger.exception("get_vacuum_reminders failed: %s", exc)
    return ""


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

    m_tidy = re.match(r"^(收拾|整理)\s*(.+)", text, re.DOTALL)
    if m_tidy and m_tidy.group(2).strip() not in ["狀態", "紀錄", "多久", "狀況", "提醒"]:
        raw_content = m_tidy.group(2).strip()

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

        # 按行拆分
        lines = [line.strip() for line in raw_content.splitlines() if line.strip()]
        tidy_records = []   # 家務紀錄
        vacuum_records = [] # 小白紀錄
        errors = []

        for line in lines:
            actions = _match_vacuum_actions(line)

            if actions:
                # ── 記到小白維護紀錄（一行可能有多個動作）──
                for action in actions:
                    try:
                        import sys
                        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                        from vacuum_tracker import add_record as vac_add
                        labels = vac_add(action, user=member or "家人", note="")
                        vacuum_records.extend(labels)
                    except Exception as exc:
                        logger.exception("vacuum add_record failed: %s", exc)
                        errors.append(line)
            else:
                # ── 記到 Google Sheets 收拾紀錄 ──
                area = _detect_area(line)
                content = line
                if area == "未分類":
                    if content.startswith("自己 ") or content.startswith("我的 "):
                        area = "自己"
                        content = content[3:].strip()
                    elif content.startswith("公共 ") or content.startswith("公用 "):
                        area = "公共"
                        content = content[3:].strip()

                try:
                    add_tidy_log(member, area, content)
                    area_emoji = "🏠" if area == "自己" else "🛋" if area == "公共" else "📦"
                    tidy_records.append(f"{area_emoji} {content}（{area}區域）")
                except Exception as exc:
                    logger.exception("add_tidy_log failed: %s", exc)
                    errors.append(line)

        # 組裝回覆
        parts = []
        if tidy_records:
            parts.append("🧹 家務紀錄\n" + "\n".join(tidy_records))
        if vacuum_records:
            parts.append("🤖 小白維護\n" + "\n".join(vacuum_records))

        # 超期提醒
        reminders = _get_vacuum_reminders()
        if reminders:
            parts.append("⚠️ 維護提醒\n" + reminders)

        if parts:
            header = f"✅ 已記錄 {len(tidy_records) + len(vacuum_records)} 項！\n\n"
            body = "\n\n".join(parts)
            footer = f"\n\n👤 紀錄人：{member}\n傳「收拾」查看今天全家紀錄"
            reply(reply_token, header + body + footer)
        elif errors:
            reply(reply_token, "❌ 記錄失敗，請稍後再試")
        else:
            reply(reply_token, "沒有偵測到可記錄的內容 😅")
        return True

    return False
