"""
每週總結 — 週日 23:59 CST
發送本週點數統計，點數下週自動從頭計算（依日期 >= 週一 filter）
"""

import os
import requests
from sheets import get_members, get_weekly_points, get_declutter_list

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

    sorted_members = sorted(members, key=lambda m: pts.get(m, 0), reverse=True)

    medals = ["🥇", "🥈", "🥉"]
    lines = ["🗓️ 本週家事點數總結！\n"]
    for i, m in enumerate(sorted_members):
        p = pts.get(m, 0)
        p_str = f"{p:.2f}".rstrip('0').rstrip('.')
        medal = medals[i] if i < 3 else "  "
        status = "✅ 達標" if p >= POINTS_THRESHOLD else "❌ 未達標"
        lines.append(f"{medal} {m}：{p_str} 點 {status}")

    lines.append(f"\n（每週目標：{POINTS_THRESHOLD} 點）")
    lines.append("新的一週從明天開始，大家繼續加油 💪")

    # 斷捨離待定提醒
    pending = get_declutter_list(only_pending=True)
    if pending:
        lines.append(f"\n\n🗂️ 斷捨離待定區還有 {len(pending)} 項：")
        for it in pending[:5]:
            lines.append(f"  • {it['name']}")
        if len(pending) > 5:
            lines.append(f"  ...還有 {len(pending)-5} 項")
        lines.append("趁週末清一清吧！")

    push("\n".join(lines))
    print("Weekly summary sent.")


main()
