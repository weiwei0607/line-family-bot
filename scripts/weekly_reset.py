"""
每週重置 — 週一 00:00 CST
重置每週循環的家事，並發送上週點數總結
"""

import os
import requests
from sheets import get_members, get_weekly_points, get_chores, reset_chore

GROUP_ID = os.environ["LINE_GROUP_ID"]
CHANNEL_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
POINTS_THRESHOLD = int(os.environ.get("POINTS_THRESHOLD", "5"))


def push(text: str):
    requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers={
            "Authorization": f"Bearer {CHANNEL_TOKEN}",
            "Content-Type": "application/json",
        },
        json={
            "to": GROUP_ID,
            "messages": [{"type": "text", "text": text[:4900]}],
        },
        timeout=10,
    )


def main():
    members = get_members()
    pts = get_weekly_points()

    # 上週總結
    lines = ["🗓️ 上週家事點數總結！\n"]
    sorted_members = sorted(members, key=lambda m: pts.get(m, 0), reverse=True)

    medals = ["🥇", "🥈", "🥉"]
    for i, m in enumerate(sorted_members):
        p = pts.get(m, 0)
        medal = medals[i] if i < 3 else "  "
        status = "✅ 達標" if p >= POINTS_THRESHOLD else "❌ 未達標"
        lines.append(f"{medal} {m}：{p} 點 {status}")

    lines.append(f"\n（每週目標：{POINTS_THRESHOLD} 點）")
    lines.append("\n新的一週開始囉！大家繼續加油 💪")

    push("\n".join(lines))

    # 重置每週循環家事（category 含「每週」的）
    chores = get_chores()
    for c in chores:
        if "每週" in c.get("category", "") and c["status"] == "已完成":
            reset_chore(c["name"])

    print("Weekly reset done.")


main()
