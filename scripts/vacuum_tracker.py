#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Family Bot - 掃地機器人（小白）＋ 家務維護紀錄模組

用法（在 LINE 打字）：
  幫小白洗集塵盒
  收拾：自己區域資源回收、掃地機器人集塵盒清洗濾網更換、公共區域過期零食清理空罐子清洗
  小白狀態
  小白多久沒清

儲存：本地 JSON（scripts/data/vacuum_log.json）
"""

import json
import os
import re
from datetime import datetime
from typing import Optional, Dict, Any, List
from zoneinfo import ZoneInfo

# ── 設定 ──────────────────────────────────────────────────────────────
DATA_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(DATA_DIR, "data", "vacuum_log.json")

TZ = ZoneInfo("Asia/Taipei")

# 建議維護頻率（用於提醒）
SCHEDULE = {
    # 小白維護
    "empty_dustbin":  {"days": 7,   "label": "倒集塵盒",       "icon": "🗑️",  "category": "小白"},
    "clean_dustbin":  {"days": 14,  "label": "洗集塵盒",       "icon": "🧼",  "category": "小白"},
    "clean_brush":    {"days": 14,  "label": "清理主刷",       "icon": "🌀",  "category": "小白"},
    "replace_brush":  {"days": 180, "label": "換主刷",         "icon": "🔄",  "category": "小白"},
    "replace_filter": {"days": 30,  "label": "換濾網",         "icon": "🫁",  "category": "小白"},
    # 家務
    "recycle":        {"days": 7,   "label": "資源回收",       "icon": "♻️",  "category": "家務"},
    "clean_public":   {"days": 3,   "label": "公共區域清理",   "icon": "🧹",  "category": "家務"},
    "clean_fridge":   {"days": 14,  "label": "清理過期食品",   "icon": "🥫",  "category": "家務"},
}

# 自然語言關鍵字對應 action（正序 + 反序）
KEYWORDS = {
    "empty_dustbin":  ["倒集塵盒", "倒垃圾", "清集塵盒"],
    "clean_dustbin":  ["洗集塵盒", "洗塵盒",
                       "集塵盒清洗", "集塵盒清理", "塵盒清洗", "集塵盒清"],
    "clean_brush":    ["清理主刷", "清主刷", "洗主刷", "清理滾刷", "清滾刷",
                       "主刷清理", "滾刷清理", "主刷清洗", "滾刷清洗"],
    "replace_brush":  ["換主刷", "換滾刷", "主刷換新", "換新主刷",
                       "主刷更換", "滾刷更換"],
    "replace_filter": ["換濾網", "濾網換新", "換新濾網", "換hepa", "換HEPA",
                       "濾網更換", "HEPA更換", "hepa更換"],
    "recycle":        ["資源回收", "回收", "分類回收"],
    "clean_public":   ["公共區域清理", "公共區域", "清理公共區域", "公共區域打掃",
                       "空罐子清洗", "清理空罐", "清理空瓶子"],
    "clean_fridge":   ["過期零食清理", "清理過期零食", "過期食品清理", "清理過期食品",
                       "過期零食", "過期食品"],
}

QUERY_KEYWORDS = ["小白狀態", "小白紀錄", "小白多久", "小白狀況", "小白提醒",
                  "家務狀態", "家務紀錄", "家務多久", "收拾狀態", "整理狀態"]

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
    return datetime.now(TZ).isoformat()


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def _days_since(ts: str) -> int:
    return (datetime.now(TZ) - _parse(ts)).days


def _fmt_date(ts: str) -> str:
    dt = _parse(ts)
    return dt.strftime("%Y/%m/%d %H:%M")


# ── 核心邏輯 ──────────────────────────────────────────────────────────

def add_record(action: str, user: str = "家人", note: str = "") -> list[str]:
    """新增一筆維護紀錄（洗集塵盒時順便記倒集塵盒）"""
    if action not in SCHEDULE:
        return [f"❌ 不認識的維護項目：{action}"]

    data = _load()
    labels = []

    # 洗集塵盒時順便記倒集塵盒（洗一定會倒）
    if action == "clean_dustbin":
        empty_rec = {
            "action": "empty_dustbin",
            "user": user,
            "timestamp": _now(),
            "note": note,
        }
        data["records"].append(empty_rec)
        e = SCHEDULE["empty_dustbin"]
        labels.append(f"{e['icon']} {e['label']}")

    record = {
        "action": action,
        "user": user,
        "timestamp": _now(),
        "note": note,
    }
    data["records"].append(record)
    _save(data)

    s = SCHEDULE[action]
    labels.append(f"{s['icon']} {s['label']}")
    return labels


def get_status() -> str:
    """查詢目前狀態（按類別分組，超期項目醒目提示）"""
    data = _load()
    records = data.get("records", [])
    device = data.get("device_name", "小白")

    if not records:
        return (
            f"🤖 {device} 目前還沒有任何維護紀錄。\n"
            f"打「幫小白洗集塵盒」或「收拾」之類的就可以開始紀錄囉！"
        )

    # 按 category 分組
    categories = {}
    for action, s in SCHEDULE.items():
        cat = s["category"]
        if cat not in categories:
            categories[cat] = []
        categories[cat].append((action, s))

    lines = []
    overdue_alerts = []

    for cat, items in categories.items():
        cat_lines = []
        for action, s in items:
            relevant = [r for r in records if r["action"] == action]
            if relevant:
                latest = max(relevant, key=lambda r: r["timestamp"])
                days = _days_since(latest["timestamp"])
                overdue = days > s["days"]
                if overdue:
                    status_emoji = "🔴"
                    overdue_alerts.append(
                        f"{s['icon']} {s['label']} 已過 {days} 天（建議每{s['days']}天）"
                    )
                else:
                    status_emoji = "🟢"
                hint = f"（建議每{s['days']}天）"
                cat_lines.append(
                    f"  {s['icon']} {s['label']}: {status_emoji} 已過 {days} 天 {hint}\n"
                    f"     上次：{_fmt_date(latest['timestamp'])} by {latest['user']}"
                )
            else:
                cat_lines.append(
                    f"  {s['icon']} {s['label']}: ⚪ 尚無紀錄\n"
                    f"     （建議每{s['days']}天）"
                )

        if cat_lines:
            lines.append(f"\n📂 {cat}")
            lines.extend(cat_lines)

    # 超期提醒放在最前面
    if overdue_alerts:
        header = ["⚠️ 以下項目已超期，該處理囉！"] + [f"  • {a}" for a in overdue_alerts]
        lines = header + lines
    else:
        lines = ["✅ 一切正常，所有項目都在建議週期內 💚"] + lines

    return "\n".join(lines)


# ── 指令解析 ──────────────────────────────────────────────────────────

def parse_message(text: str) -> Optional[Dict[str, Any]]:
    """
    解析 LINE 訊息，回傳 {'type': 'record'|'query', 'actions': [...], 'note': ...}
    解析不到則回傳 None
    """
    t_raw = text.strip()
    t = t_raw.replace(" ", "").replace("　", "")

    # 查詢指令
    for kw in QUERY_KEYWORDS:
        if kw in t or kw in t_raw:
            return {"type": "query", "actions": []}

    # 紀錄指令：收集所有匹配到的 action（一句話可能包含多個動作）
    matched_actions = []
    for action, keywords in KEYWORDS.items():
        for kw in keywords:
            if kw in t:
                matched_actions.append(action)
                break  # 該 action 已匹配，不再比對其他關鍵字

    if matched_actions:
        note = ""
        m = re.search(r"備註[：:]\s*(.+)", t_raw)
        if m:
            note = m.group(1).strip()
        return {"type": "record", "actions": matched_actions, "note": note}

    return None


def handle(text: str, user: str = "家人") -> str:
    """LINE Webhook 收到訊息時直接呼叫這個函式"""
    parsed = parse_message(text)
    if not parsed:
        return ""  # 不回覆（讓其他模組處理）

    if parsed["type"] == "query":
        return get_status()

    # 依序記錄多個動作
    all_labels = []
    for action in parsed["actions"]:
        labels = add_record(action, user=user, note=parsed.get("note", ""))
        all_labels.extend(labels)

    if not all_labels:
        return ""

    # 去重（洗集塵盒會連帶記倒集塵盒，同一批可能重複）
    seen = set()
    unique_labels = []
    for lbl in all_labels:
        if lbl not in seen:
            seen.add(lbl)
            unique_labels.append(lbl)

    header = f"✅ 已紀錄 {len(unique_labels)} 項！\n"
    body = "\n".join(f"  {r}" for r in unique_labels)
    footer = f"\n👤 紀錄人：{user}\n🕐 {_fmt_date(_now())}"
    return header + body + footer


# ── 測試 ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    test_msg = "收拾\n自己區域的資源回收\n掃地機器人的集塵盒清洗濾網更換\n公共區域的過期零食清理空罐子清洗"
    print("=== 多動作測試 ===")
    print(handle(test_msg, user="姊姊"))
    print()
    print("=== 狀態查詢 ===")
    print(handle("小白狀態"))
