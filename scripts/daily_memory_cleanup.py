"""
每日對話紀錄清理 + 每週總結
- 每天刪除無意義的指令噪音（純功能指令、查詢等）
- 保留有意義的對話（閒聊、分享、情感、討論）
- 每週一生成對話亮點摘要，發送到群組
"""

import os
import re
import json
import logging
from datetime import datetime, timezone, timedelta
from sheets import _read, _append, _get_service, _get_sheet_id

logger = logging.getLogger(__name__)
TW_TZ = timezone(timedelta(hours=8))
_TAB = "對話紀錄"

# 無意義指令的正則清單（直接快速過濾，省 API 額度）
_NOISE_PATTERNS = [
    r"^天氣\s*",
    r"^查天氣\s*",
    r"^查帳\s*",
    r"^記帳\s+",
    r"^買\s+",
    r"^買好了\s+",
    r"^購物清單\s*",
    r"^家事清單\s*",
    r"^完成\s+",
    r"^查點數\s*",
    r"^點數\s*",
    r"^說明\s*",
    r"^指令\s*",
    r"^help\s*",
    r"^QR\s+",
    r"^縮網址\s+",
    r"^匯率\s*",
    r"^金價\s*",
    r"^BMI\s+",
    r"^熱量\s+",
    r"^消耗熱量\s+",
    r"^倒數\s+",
    r"^抽籤\s+",
    r"^搖骰子\s*",
    r"^猜拳\s+",
    r"^配對\s+",
    r"^誰請客\s*",
    r"^貓貓\s*",
    r"^狗狗\s*",
    r"^狐狸\s*",
    r"^柴柴\s*",
    r"^熊貓\s*",
    r"^無尾熊\s*",
    r"^浣熊\s*",
    r"^今日宇宙\s*",
    r"^抽寶可夢\s*",
    r"^今日食譜\s*",
    r"^推薦電影\s*",
    r"^冷笑話\s*",
    r"^冷知識\s*",
    r"^給我建議\s*",
    r"^動漫圖\s*",
    r"^激勵名言\s*",
    r"^找歌\s+",
    r"^找影片\s+",
    r"^查電影\s+",
    r"^電影台詞\s*",
    r"^在哪看\s+",
    r"^動漫語錄\s*",
    r"^川普語錄\s*",
    r"^隨機梗圖\s*",
    r"^諾里斯\s*",
    r"^新聞\s*",
    r"^今日運動\s*",
    r"^找運動\s+",
    r"^今日調酒\s*",
    r"^來一題\s*",
    r"^積分\s*",
    r"^我好無聊\s*",
    r"^食譜\s+",
    r"^國家\s+",
    r"^找書\s+",
    r"^寶可夢\s+",
    r"^翻\s+",
    r"^摘要\s+",
    r"^改寫\s+",
    r"^查日文\s+",
    r"^漢字\s+",
    r"^查西文\s+",
    r"^今日日文單字\s*",
    r"^今日西文單字\s*",
    r"^今日漢字\s*",
    r"^說\s+",
    r"^念\s+",
    r"^唸\s+",
    r"^讀\s+",
    r"^打卡\s+",
    r"^設目標\s*",
    r"^查目標\s*",
    r"^進度\s*",
    r"^今日打卡\s*",
    r"^我的打卡\s*",
    r"^上週期\s*",
    r"^幾天了\s*",
    r"^今天第幾天\s*",
    r"^幫我想目標\s*",
    r"^提醒我\s+",
    r"^待辦\s*",
    r"^完成待辦\s+",
    r"^查待辦\s*",
    r"^查提醒\s*",
    r"^叫我\s+",
    r"^我是\s+",
    r"^本週總結\s*",
    r"^今日運勢\s*",
    r"^今日天蠍\s*",
    r"^今日雙子\s*",
    r"^今日金牛\s*",
    r"^今日處女\s*",
    r"^今日巨蟹\s*",
    r"^今日獅子\s*",
    r"^今日天秤\s*",
    r"^今日天枰\s*",
    r"^今日射手\s*",
    r"^今日摩羯\s*",
    r"^今日水瓶\s*",
    r"^今日雙魚\s*",
    r"^今日牡羊\s*",
    r"^配對星座\s+",
    r"^去背\s*",
    r"^傳音訊\s*",
    r"^Shazam\s*",
    r"^聽歌\s*",
    r"^機器人\s*",
    r"^\s*$",  # 空行
]
_NOISE_RE = [re.compile(p, re.IGNORECASE) for p in _NOISE_PATTERNS]


def _is_noise(speaker: str, message: str) -> bool:
    """快速判斷是否為無意義指令噪音。"""
    # 機器人自己的回覆（除非是 @機器人 的問答上下文）
    if speaker == "機器人" and not message.startswith("@"):
        return True
    # 匹配噪音正則
    for r in _NOISE_RE:
        if r.match(message):
            return True
    return False


def _get_gemini_summary(meaningful_rows: list[list]) -> str:
    """呼叫 Gemini 生成本週對話亮點摘要。"""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return "（缺少 GEMINI_API_KEY，無法生成 AI 摘要）"

    # 組裝本週對話（最多 80 條，避免 token 爆炸）
    lines = []
    for r in meaningful_rows[-80:]:
        if len(r) >= 3:
            ts = r[0][:16]  # 只取日期+時間
            speaker = r[1]
            msg = r[2]
            lines.append(f"[{ts}] {speaker}: {msg}")
    chat_text = "\n".join(lines)

    prompt = f"""你是一個家庭群組觀察員。以下是本週家人在群組中的對話紀錄。
請用溫暖、幽默的語氣，整理出 3-5 個「本週亮點」或有趣觀察。

對話紀錄：
{chat_text}

請用繁體中文，直接輸出摘要（不要標題、不要 markdown 程式碼區塊），每個亮點一行，前面加上對應的 emoji。"""

    try:
        import requests
        resp = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent",
            headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=30,
        )
        data = resp.json()
        text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        return text.strip() or "（本週沒有特別的對話亮點）"
    except Exception as exc:
        logger.warning("Gemini summary failed: %s", exc)
        return "（AI 摘要生成失敗）"


def main():
    today = datetime.now(TW_TZ)
    is_monday = today.weekday() == 0

    logger.info("daily_memory_cleanup: %s, is_monday=%s", today.strftime("%Y-%m-%d"), is_monday)

    # 1. 讀取對話紀錄
    rows = _read(_TAB, "A2:D5000")
    if not rows:
        push_text_to_group("📭 本週還沒有對話紀錄")
        return

    # 2. 分類：有意義 vs 噪音
    meaningful = []
    noise_count = 0
    for r in rows:
        if len(r) < 3:
            continue
        ts, speaker, message = r[0], r[1], r[2]
        if _is_noise(speaker, message):
            noise_count += 1
        else:
            meaningful.append(r)

    # 3. 如果噪音很多，重寫 Sheets（保留有意義的）
    if noise_count > 10:
        try:
            svc = _get_service()
            sid = _get_sheet_id()
            total = len(rows)
            # 清除舊資料
            svc.spreadsheets().values().clear(
                spreadsheetId=sid, range=f"{_TAB}!A2:D{total + 1}"
            ).execute()
            # 寫回有意義的
            if meaningful:
                svc.spreadsheets().values().update(
                    spreadsheetId=sid,
                    range=f"{_TAB}!A2",
                    valueInputOption="USER_ENTERED",
                    body={"values": meaningful},
                ).execute()
            logger.info("Cleaned %d noise rows, kept %d meaningful", noise_count, len(meaningful))
        except Exception as exc:
            logger.warning("Sheets cleanup failed: %s", exc)

    # 4. 生成本週對話摘要
    summary = _get_gemini_summary(meaningful)

    # 5. 每週一把 AI 摘要寫入 Sheets「每週摘要」tab
    if is_monday:
        try:
            from sheets import _get_service, _get_sheet_id
            svc = _get_service()
            sid = _get_sheet_id()
            # 確保 tab 存在
            sheet_metadata = svc.spreadsheets().get(spreadsheetId=sid).execute()
            tabs = [s['properties']['title'] for s in sheet_metadata.get('sheets', [])]
            if "每週摘要" not in tabs:
                svc.spreadsheets().batchUpdate(
                    spreadsheetId=sid,
                    body={"requests": [{"addSheet": {"properties": {"title": "每週摘要"}}}]},
                ).execute()
            week_label = today.strftime("%Y-%m-%d")
            svc.spreadsheets().values().append(
                spreadsheetId=sid,
                range="每週摘要!A1",
                valueInputOption="USER_ENTERED",
                body={"values": [[week_label, summary]]},
            ).execute()
            logger.info("Weekly summary saved to Sheets: %s", week_label)
        except Exception as exc:
            logger.warning("Save weekly summary to Sheets failed: %s", exc)
    logger.info("Daily cleanup done. noise=%d meaningful=%d", noise_count, len(meaningful))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
