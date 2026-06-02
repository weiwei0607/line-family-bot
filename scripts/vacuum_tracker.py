#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Family Bot - 掃地機器人（小白）維護紀錄模組

用法（在 LINE 打字）：
  幫小白洗集塵盒
  小白清理主刷
  幫小白換主刷
  小白換濾網
  小白狀態
  小白多久沒清

儲存：本地 JSON（~/family-bot-features/vacuum-tracker/data/vacuum_log.json）
"""

import json
import os
import re
from datetime import datetime, timezone
from typing import Optional, Dict, Any

# ── 設定 ──────────────────────────────────────────────────────────────
DATA_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(DATA_DIR, "data", "vacuum_log.json")

# 建議維護頻率（用於提醒）
SCHEDULE = {
    "clean_dustbin":  {"days": 7,  "label": "洗集塵盒",  "icon": "🗑️"},
    "clean_brush":    {"days": 14, "label": "清理主刷",  "icon": "🌀"},
    "replace_brush":  {"days": 180,"label": "換主刷",    "icon": "🔄"},
    "replace_filter": {"days": 90, "label": "換濾網",    "icon": "🫁"},
}

# 自然語言關鍵字對應 action
KEYWORDS = {
    "clean_dustbin":  ["洗集塵盒", "倒集塵盒", "清集塵盒", "洗塵盒", "倒垃圾",
                       "集塵盒清洗", "集塵盒清理", "塵盒清洗", "集塵盒清"],
    "clean_brush":    ["清理主刷", "清主刷", "洗主刷", "清理滾刷", "清滾刷",
                       "主刷清理", "滾刷清理", "主刷清洗", "滾刷清洗"],
    "replace_brush":  ["換主刷", "換滾刷", "主刷換新", "換新主刷",
                       "主刷更換", "滾刷更換"],
    "replace_filter": ["換濾網", "濾網換新", "換新濾網", "換hepa", "換HEPA",
                       "濾網更換", "HEPA更換", "hepa更換"],
}

QUERY_KEYWORDS = ["小白狀態", "小白紀錄", "小白多久", "小白狀況", "小白提醒"]

# ── 儲存層 ────────────────────────────────────────────────────────────

def _load() -> Dict[str, Any]:
    if not os.path.exists(DATA_FILE):
        return {"records": [], "device_name": "小白"}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def _days_since(ts: str) -> int:
    return (datetime.now(timezone.utc).astimezone() - _parse(ts)).days


def _fmt_date(ts: str) -> str:
    dt = _parse(ts)
    return dt.strftime("%Y/%m/%d %H:%M")

# ── 核心邏輯 ──────────────────────────────────────────────────────────

def add_record(action: str, user: str = "家人", note: str = "") -> str:
    """新增一筆維護紀錄，回傳要回覆給 LINE 的文字"""
    if action not in SCHEDULE:
        return f"❌ 不認識的維護項目：{action}"

    data = _load()
    record = {
        "action": action,
        "user": user,
        "timestamp": _now(),
        "note": note,
    }
    data["records"].append(record)
    _save(data)

    s = SCHEDULE[action]
    return (
        f"✅ 已紀錄！\n"
        f"{s['icon']} {s['label']}\n"
        f"👤 紀錄人：{user}\n"
        f"🕐 {_fmt_date(record['timestamp'])}"
    )


def get_status() -> str:
    """查詢小白目前狀態"""
    data = _load()
    records = data.get("records", [])
    device = data.get("device_name", "小白")

    if not records:
        return (
            f"🤖 {device} 目前還沒有任何維護紀錄。\n"
            f"打「幫小白洗集塵盒」之類的就可以開始紀錄囉！"
        )

    lines = [f"🤖 {device} 維護狀態一覽"]
    lines.append("─" * 28)

    for action, s in SCHEDULE.items():
        # 找出該項目的最新紀錄
        relevant = [r for r in records if r["action"] == action]
        if relevant:
            latest = max(relevant, key=lambda r: r["timestamp"])
            days = _days_since(latest["timestamp"])
            overdue = days > s["days"]
            status_emoji = "🔴" if overdue else "🟢"
            hint = f"（建議每{s['days']}天）"
            lines.append(
                f"{s['icon']} {s['label']}: {status_emoji} 已過 {days} 天 {hint}\n"
                f"   上次：{_fmt_date(latest['timestamp'])} by {latest['user']}"
            )
        else:
            lines.append(
                f"{s['icon']} {s['label']}: ⚪ 尚無紀錄\n"
                f"   （建議每{s['days']}天）"
            )

    # 給出下一步建議
    lines.append("\n📌 下一步建議：")
    suggestions = []
    for action, s in SCHEDULE.items():
        relevant = [r for r in records if r["action"] == action]
        if not relevant:
            suggestions.append(f"{s['icon']} 先紀錄一次「{s['label']}」")
        else:
            latest = max(relevant, key=lambda r: r["timestamp"])
            days = _days_since(latest["timestamp"])
            if days > s["days"]:
                suggestions.append(f"{s['icon']} 該{s['label']}了！（已過 {days} 天）")

    if suggestions:
        lines.append("\n".join(f"  • {sg}" for sg in suggestions[:3]))
    else:
        lines.append("  • 一切正常，小白很健康 💚")

    return "\n".join(lines)


# ── 指令解析 ──────────────────────────────────────────────────────────

def parse_message(text: str) -> Optional[Dict[str, str]]:
    """
    解析 LINE 訊息，回傳 {'type': 'record'|'query', 'action': ..., 'note': ...}
    解析不到則回傳 None
    
    支援有無空格、有無「小白」前綴的各種說法
    """
    # 去掉前後空白 + 去掉所有半形/全形空格，讓「幫 小白 洗 集塵盒」也能命中
    t_raw = text.strip()
    t = t_raw.replace(" ", "").replace("　", "")

    # 查詢指令（也做去空白版比對）
    for kw in QUERY_KEYWORDS:
        if kw in t or kw in t_raw:
            return {"type": "query"}

    # 紀錄指令：比對關鍵字（去空白後的字串）
    for action, keywords in KEYWORDS.items():
        for kw in keywords:
            if kw in t:   # 關鍵字本身不含空格，直接用去空白後的字串比對
                # 嘗試抓備註（用原始字串抓，避免去空白後把備註空格也清掉）
                note = ""
                m = re.search(r"備註[：:]\s*(.+)", t_raw)
                if m:
                    note = m.group(1).strip()
                return {"type": "record", "action": action, "note": note}

    return None


def handle(text: str, user: str = "家人") -> str:
    """LINE Webhook 收到訊息時直接呼叫這個函式"""
    parsed = parse_message(text)
    if not parsed:
        return ""  # 不回覆（讓其他模組處理）

    if parsed["type"] == "query":
        return get_status()
    else:
        return add_record(parsed["action"], user=user, note=parsed.get("note", ""))


# ── 測試 ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # 模擬測試
    print(handle("幫小白洗集塵盒"))
    print()
    print(handle("小白清理主刷"))
    print()
    print(handle("小白狀態"))
