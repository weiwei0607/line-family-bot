"""
早安推播 — 獨立 cron 腳本
原本由 Render /daily_push HTTP 端點觸發，現在直接由 GitHub Actions 執行
"""

import os
import sys
import logging
from datetime import datetime, timezone, timedelta

# 讓 scripts/ 內的 import 能工作
sys.path.insert(0, os.path.dirname(__file__))

from sheets import get_members, get_chores, get_weekly_points, get_todos, get_setting, set_setting
from api_helpers import format_weather_block
from line_push import push_messages
from utils import send_telegram_alert

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TW_TZ = timezone(timedelta(hours=8))
POINTS_THRESHOLD = int(os.environ.get("POINTS_THRESHOLD", "5"))


def main():
    group_id = os.environ.get("LINE_GROUP_ID", "")
    if not group_id:
        logger.error("LINE_GROUP_ID not set")
        sys.exit(1)

    today_str = datetime.now(TW_TZ).strftime("%Y-%m-%d")
    # 用 Sheets「設定」tab 做最基本的去重
    if get_setting("daily_push_last_run") == today_str:
        logger.info("daily_push already sent today (%s), skipping.", today_str)
        return

    logger.info("daily_push started for %s", today_str)
    lines = ["☀️ 早安！家管助理日報\n"]
    errors = []

    # ── 天氣 ──
    try:
        weather = format_weather_block()
        lines.append(weather)
        lines.append("")
        logger.info("daily_push: weather fetched")
    except Exception as exc:
        logger.exception("daily_push weather failed")
        errors.append(f"weather: {exc}")
        lines.append("（天氣資料暫時無法取得）")
        lines.append("")

    # ── 家事清單 ──
    try:
        members = get_members()
        pts = get_weekly_points()
        chores = get_chores()
        logger.info("daily_push: members=%s chores=%s", members, len(chores))

        if chores:
            lines.append(f"📋 今日待完成家事（共 {len(chores)} 項）：")
            for c in chores[:8]:
                lines.append(f"  • {c['name']}（{c['points']}點）")
        else:
            lines.append("🎉 今日家事全部完成！大家辛苦了！")
        lines.append("")

        low_pts = [m for m in members if pts.get(m, 0) < POINTS_THRESHOLD]
        if low_pts:
            lines.append("⚠️ 本週點數還不夠的成員：")
            for m in low_pts:
                lines.append(f"  {m}：目前 {round(pts.get(m, 0), 1):g} 點（目標 {POINTS_THRESHOLD} 點）")
            lines.append("\n快去完成家事累積點數吧！💪")
        else:
            lines.append("✅ 大家本週點數都達標了，棒棒！🎉")
    except Exception as exc:
        logger.exception("daily_push chores/points failed")
        errors.append(f"chores: {exc}")
        lines.append("（家事資料暫時無法取得）")

    lines.append("\n輸入「家事清單」查看待完成家事")

    # ── 待辦事項 ──
    try:
        todos = get_todos(only_pending=True)
        today2 = datetime.now(TW_TZ).strftime("%Y-%m-%d")
        today_todos = [t for t in todos if t["date"] == today2]
        overdue_todos = [t for t in todos if t["date"] < today2]
        all_todos = today_todos + overdue_todos
        if all_todos:
            lines.append("")
            if today_todos:
                lines.append("📅 今天待辦：")
                for t in today_todos[:5]:
                    lines.append(f"  • {t['member']}｜{t['content']}")
            if overdue_todos:
                lines.append("⏰ 逾期未完成：")
                for t in overdue_todos[:3]:
                    lines.append(f"  • {t['member']}｜{t['content']}")
    except Exception as exc:
        logger.warning("daily_push todos failed: %s", exc)

    text_body = "\n".join(lines)

    # ── 推送 ──
    try:
        push_messages(group_id, [{"type": "text", "text": text_body[:4900]}])
        logger.info("daily_push: text message sent")
    except Exception as exc:
        logger.exception("daily_push text push failed")
        send_telegram_alert(f"daily_push text push failed: {type(exc).__name__}: {exc}")

    if errors:
        send_telegram_alert(f"daily_push completed with partial errors: {'; '.join(errors)}")

    # 記錄今天已發送
    try:
        set_setting("daily_push_last_run", today_str)
    except Exception as exc:
        logger.warning("Failed to update daily_push_last_run: %s", exc)

    logger.info("daily_push completed successfully for %s", today_str)


if __name__ == "__main__":
    main()
