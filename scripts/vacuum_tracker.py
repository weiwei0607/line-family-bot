#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Family Bot - 掃地機器人（小白）＋ 家務維護紀錄模組
資料儲存：Google Sheets「小白紀錄」tab（columns: timestamp, action, user, note）

用法（在 LINE 打字）：
  幫小白洗集塵盒
  收拾：掃地機器人集塵盒清洗濾網更換
  小白狀態
"""

import re
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

TZ = ZoneInfo("Asia/Taipei")
_TAB = "小白紀錄"
_TAB_ENSURED = False

SCHEDULE = {
    "empty_dustbin":  {"days": 7,   "label": "倒集塵盒",       "icon": "🗑️",  "category": "小白"},
    "clean_dustbin":  {"days": 14,  "label": "洗集塵盒",       "icon": "🧼",  "category": "小白"},
    "clean_brush":    {"days": 14,  "label": "清理主刷",       "icon": "🌀",  "category": "小白"},
    "replace_brush":  {"days": 180, "label": "換主刷",         "icon": "🔄",  "category": "小白"},
    "replace_filter": {"days": 30,  "label": "換濾網",         "icon": "🫁",  "category": "小白"},
    "recycle":        {"days": 7,   "label": "資源回收",       "icon": "♻️",  "category": "家務"},
    "clean_public":   {"days": 3,   "label": "公共區域清理",   "icon": "🧹",  "category": "家務"},
    "clean_fridge":   {"days": 14,  "label": "清理過期食品",   "icon": "🥫",  "category": "家務"},
}

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


# ── Sheets 操作 ──────────────────────────────────────────────────────────

def _ensure_tab():
    global _TAB_ENSURED
    if _TAB_ENSURED:
        return
    try:
        from sheets import _get_service, _get_sheet_id
        svc = _get_service()
        sid = _get_sheet_id()
        meta = svc.spreadsheets().get(spreadsheetId=sid).execute()
        titles = [s["properties"]["title"] for s in meta.get("sheets", [])]
        if _TAB not in titles:
            svc.spreadsheets().batchUpdate(
                spreadsheetId=sid,
                body={"requests": [{"addSheet": {"properties": {"title": _TAB}}}]},
            ).execute()
            svc.spreadsheets().values().update(
                spreadsheetId=sid,
                range=f"{_TAB}!A1:D1",
                valueInputOption="USER_ENTERED",
                body={"values": [["timestamp", "action", "user", "note"]]},
            ).execute()
        _TAB_ENSURED = True
    except Exception as exc:
        logger.warning("_ensure_tab failed: %s", exc)


def _load_records() -> list[dict]:
    """從 Google Sheets 讀取所有維護紀錄"""
    try:
        from sheets import _read
        rows = _read(_TAB, "A2:D2000")
        records = []
        for r in rows:
            if not r or len(r) < 2:
                continue
            records.append({
                "timestamp": r[0],
                "action":    r[1] if len(r) > 1 else "",
                "user":      r[2] if len(r) > 2 else "",
                "note":      r[3] if len(r) > 3 else "",
            })
        return records
    except Exception as exc:
        logger.warning("_load_records failed: %s", exc)
        return []


def _append_record(action: str, user: str, note: str):
    from sheets import _append
    _ensure_tab()
    _append(_TAB, [_now(), action, user, note])


# ── 時間工具 ──────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(TZ).isoformat()


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def _days_since(ts: str) -> int:
    return (datetime.now(TZ) - _parse(ts)).days


def _fmt_date(ts: str) -> str:
    return _parse(ts).strftime("%Y/%m/%d %H:%M")


# ── 核心邏輯 ──────────────────────────────────────────────────────────────

def add_record(action: str, user: str = "家人", note: str = "") -> list[str]:
    """新增一筆維護紀錄（洗集塵盒時順便記倒集塵盒）"""
    if action not in SCHEDULE:
        return [f"❌ 不認識的維護項目：{action}"]

    labels = []

    if action == "clean_dustbin":
        _append_record("empty_dustbin", user, note)
        e = SCHEDULE["empty_dustbin"]
        labels.append(f"{e['icon']} {e['label']}")

    _append_record(action, user, note)
    s = SCHEDULE[action]
    labels.append(f"{s['icon']} {s['label']}")
    return labels


def get_status() -> str:
    """查詢目前狀態（按類別分組，超期項目醒目提示）"""
    records = _load_records()

    if not records:
        return (
            "🤖 小白 目前還沒有任何維護紀錄。\n"
            "打「幫小白洗集塵盒」或「收拾」之類的就可以開始紀錄囉！"
        )

    categories: dict[str, list] = {}
    for action, s in SCHEDULE.items():
        cat = s["category"]
        categories.setdefault(cat, []).append((action, s))

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
                status_emoji = "🔴" if overdue else "🟢"
                if overdue:
                    overdue_alerts.append(
                        f"{s['icon']} {s['label']} 已過 {days} 天（建議每{s['days']}天）"
                    )
                cat_lines.append(
                    f"  {s['icon']} {s['label']}: {status_emoji} 已過 {days} 天（建議每{s['days']}天）\n"
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

    if overdue_alerts:
        header = ["⚠️ 以下項目已超期，該處理囉！"] + [f"  • {a}" for a in overdue_alerts]
        lines = header + lines
    else:
        lines = ["✅ 一切正常，所有項目都在建議週期內 💚"] + lines

    return "\n".join(lines)


# ── 指令解析 ──────────────────────────────────────────────────────────────

def parse_message(text: str) -> Optional[Dict[str, Any]]:
    t_raw = text.strip()
    t = t_raw.replace(" ", "").replace("　", "")

    for kw in QUERY_KEYWORDS:
        if kw in t or kw in t_raw:
            return {"type": "query", "actions": []}

    matched_actions = []
    for action, keywords in KEYWORDS.items():
        for kw in keywords:
            if kw in t:
                matched_actions.append(action)
                break

    if matched_actions:
        note = ""
        m = re.search(r"備註[：:]\s*(.+)", t_raw)
        if m:
            note = m.group(1).strip()
        return {"type": "record", "actions": matched_actions, "note": note}

    return None


def handle(text: str, user: str = "家人") -> str:
    parsed = parse_message(text)
    if not parsed:
        return ""

    if parsed["type"] == "query":
        return get_status()

    all_labels = []
    for action in parsed["actions"]:
        labels = add_record(action, user=user, note=parsed.get("note", ""))
        all_labels.extend(labels)

    if not all_labels:
        return ""

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
