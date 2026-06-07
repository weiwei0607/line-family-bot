"""
待辦連環扣提醒 — 獨立 cron 腳本
原本由 Render /check_reminders HTTP 端點觸發，現在直接由 GitHub Actions 執行
"""

import os
import sys
import logging
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))

from sheets import get_todos, update_todo_reminder, TW_TZ
from line_push import push_messages
from tts_store import kv_get, kv_set

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    group_id = os.environ.get("LINE_GROUP_ID", "")
    if not group_id:
        logger.error("LINE_GROUP_ID not set")
        sys.exit(1)

    now = datetime.now(TW_TZ)
    today = now.strftime("%Y-%m-%d")
    todos = get_todos(only_pending=True)
    sent = 0

    def _push(msg):
        nonlocal sent
        push_messages(group_id, [{"type": "text", "text": msg}])
        sent += 1

    def _send_reminder(t, msg, new_count):
        _push(msg)
        update_todo_reminder(t["row"], new_count)

    for t in todos:
        try:
            if t["date"] != today:
                continue
            time_str = t.get("time", "").strip()
            reminded = t.get("reminded_count", 0)
            member = t["member"]
            content = t["content"]

            if time_str:
                # 有時間：奪命連環扣（最多 3 次）
                if reminded >= 3:
                    continue
                try:
                    todo_hour, todo_min = int(time_str[:2]), int(time_str[3:5])
                except (ValueError, IndexError):
                    continue
                due = datetime(now.year, now.month, now.day, todo_hour, todo_min, tzinfo=TW_TZ)
                if reminded == 0 and now > due + timedelta(hours=1):
                    continue
                trigger = due + timedelta(minutes=30 * reminded)
                if now < trigger:
                    continue

                if reminded == 0:
                    msg = f"🔔 提醒時間到！\n📌 {member}：{content}\n\n完成後傳「完成待辦 {content[:10]}」，否則 30 分鐘後會繼續叫你 😤"
                else:
                    bells = "🔔" * (reminded + 1)
                    remaining = 3 - reminded - 1
                    suffix = f"（還差 {remaining} 次就放棄了）" if remaining > 0 else "（最後一次了，拜託快去做！）"
                    msg = f"{bells} 還沒做喔！\n📌 {member}：{content}\n完成後傳「完成待辦 {content[:10]}」{suffix}"
                _send_reminder(t, msg, reminded + 1)
            else:
                # 沒時間：晚上 20:00 提醒一次
                if reminded >= 1:
                    continue
                if now.hour < 20:
                    continue
                msg = f"🔔 今日待辦提醒！\n📌 {member}：{content}"
                _send_reminder(t, msg, 1)
        except Exception as _e:
            logger.warning("check_reminders: error processing todo row %s: %s", t.get("row"), _e)

    # 前一天晚上提醒
    if now.hour >= 20:
        tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
        for t in todos:
            try:
                if t["date"] != tomorrow:
                    continue
                preday_key = f"preday:{t['date']}:{t['member']}:{t['content'][:20]}"
                if kv_get(preday_key):
                    continue
                member = t["member"]
                content = t["content"]
                msg = f"📅 明天待辦提醒！\n📌 {member}：{content}\n\n完成後傳「完成待辦 {content[:10]}」"
                _push(msg)
                kv_set(preday_key, "1", ttl_seconds=90000)
            except Exception as _e:
                logger.warning("check_reminders: error processing pre-day todo row %s: %s", t.get("row"), _e)

    logger.info("check_reminders: sent %d reminders", sent)


if __name__ == "__main__":
    main()
