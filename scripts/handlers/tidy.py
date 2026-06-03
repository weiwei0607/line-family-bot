"""
Family bot tidy-log handlers.
Record and view tidy/cleaning logs.
Also detects vacuum-robot maintenance keywords and logs them simultaneously.
"""

import os
import re
import sys
import logging
from linebot.v3.messaging import ApiClient, MessagingApi
from sheets import add_tidy_log, format_tidy_summary, _detect_area, get_today_tidy_type_count, get_tidy_debt
from line_push import reply_text as reply

logger = logging.getLogger(__name__)

# 從 vacuum_tracker 動態取得小白關鍵字，避免維護兩份
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from vacuum_tracker import KEYWORDS as _VT_KEYWORDS, SCHEDULE as _VT_SCHEDULE, add_record as vac_add, _load_records, _days_since
_VACUUM_KEYWORDS = {
    action: kws
    for action, kws in _VT_KEYWORDS.items()
    if _VT_SCHEDULE.get(action, {}).get("category") == "小白"
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
        records = _load_records()
        alerts = []
        for action, s in _VT_SCHEDULE.items():
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

    # ── 補收拾（補記過去欠下的）──
    m_makeup = re.match(r"^補收拾\s*(.+)", text, re.DOTALL)
    if m_makeup:
        raw_content = m_makeup.group(1).strip()
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

        debt = get_tidy_debt()
        member_debt = dict(debt.get(member, {"自己": 0, "公共": 0}))  # local copy

        lines_input = [l.strip() for l in raw_content.splitlines() if l.strip()]
        makeup_records = []
        rejected = []

        for line in lines_input:
            area = _detect_area(line)
            content = line
            if area == "未分類":
                if content.startswith("自己 ") or content.startswith("我的 "):
                    area = "自己"; content = content[3:].strip()
                elif content.startswith("公共 ") or content.startswith("公用 "):
                    area = "公共"; content = content[3:].strip()
                else:
                    area = "自己"  # 預設

            if area not in ("自己", "公共"):
                area = "自己"

            if member_debt.get(area, 0) <= 0:
                area_desc = "自己的地方" if area == "自己" else "家裡"
                rejected.append(f"• {line}（本週沒有欠收拾{area_desc}）")
                continue

            makeup_area = f"補{area}"
            try:
                add_tidy_log(member, makeup_area, content)
                member_debt[area] = max(0, member_debt[area] - 1)
                makeup_records.append(f"📝 {content}（補{area}）")
            except Exception as exc:
                logger.exception("add_tidy_log makeup failed: %s", exc)
                rejected.append(f"• {line}（記錄失敗）")

        parts = []
        if makeup_records:
            parts.append("✅ 補收拾成功\n" + "\n".join(makeup_records))
        if rejected:
            parts.append("❌ 以下無法補記\n" + "\n".join(rejected))
        reply(reply_token, ("\n\n".join(parts) or "沒有偵測到可補記的內容") +
              f"\n\n👤 {member}｜傳「收拾」查看欠收拾統計")
        return True

    # ── 一般收拾 ──
    m_tidy = re.match(r"^(收拾|整理)\s*(.+)", text, re.DOTALL)
    if m_tidy and m_tidy.group(2).strip() not in ["狀態", "紀錄", "多久", "狀況", "提醒"]:
        raw_content = m_tidy.group(2).strip()

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

        # 取今天已有的紀錄次數（每類上限1次）
        today_count = get_today_tidy_type_count(member)

        lines_input = [line.strip() for line in raw_content.splitlines() if line.strip()]
        tidy_records = []
        vacuum_records = []
        already_done = []
        errors = []

        for line in lines_input:
            actions = _match_vacuum_actions(line)
            if actions:
                for action in actions:
                    try:
                        labels = vac_add(action, user=member or "家人", note="")
                        vacuum_records.extend(labels)
                    except Exception as exc:
                        logger.exception("vacuum add_record failed: %s", exc)
                        errors.append(line)
                continue

            area = _detect_area(line)
            content = line
            if area == "未分類":
                if content.startswith("自己 ") or content.startswith("我的 "):
                    area = "自己"; content = content[3:].strip()
                elif content.startswith("公共 ") or content.startswith("公用 "):
                    area = "公共"; content = content[3:].strip()

            # 每日上限檢查
            if area in ("自己", "公共") and today_count.get(area, 0) >= 1:
                already_done.append((area, content))
                today_count[area] = today_count.get(area, 0) + 1  # 防同批次重複
                continue

            try:
                add_tidy_log(member, area, content)
                if area in ("自己", "公共"):
                    today_count[area] = today_count.get(area, 0) + 1
                area_emoji = "🏠" if area == "自己" else "🛋" if area == "公共" else "📦"
                tidy_records.append(f"{area_emoji} {content}（{area}區域）")
            except Exception as exc:
                logger.exception("add_tidy_log failed: %s", exc)
                errors.append(line)

        parts = []
        if tidy_records:
            parts.append("🧹 家務紀錄\n" + "\n".join(tidy_records))
        if vacuum_records:
            parts.append("🤖 小白維護\n" + "\n".join(vacuum_records))

        reminders = _get_vacuum_reminders()
        if reminders:
            parts.append("⚠️ 維護提醒\n" + reminders)

        if already_done:
            debt = get_tidy_debt()
            member_debt = debt.get(member, {"自己": 0, "公共": 0})
            skip_lines = []
            for area, content in already_done:
                has_debt = member_debt.get(area, 0) > 0
                hint = f"（有欠收拾可傳「補收拾 {content}」補記）" if has_debt else "（今天不需要再記）"
                skip_lines.append(f"• {content}{hint}")
            parts.append(f"⚠️ 今天{'/'.join(set(a for a, _ in already_done))}已記過，以下略過\n" + "\n".join(skip_lines))

        if parts:
            header = f"✅ 已記錄 {len(tidy_records) + len(vacuum_records)} 項！\n\n" if (tidy_records or vacuum_records) else ""
            body = "\n\n".join(parts)
            footer = f"\n\n👤 紀錄人：{member}｜傳「收拾」查看今天全家紀錄"
            reply(reply_token, header + body + footer)
        elif errors:
            reply(reply_token, "❌ 記錄失敗，請稍後再試")
        else:
            reply(reply_token, "沒有偵測到可記錄的內容 😅")
        return True

    return False
