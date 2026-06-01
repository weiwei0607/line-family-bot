"""
Family bot finance handlers.
Currency, gold, stock, crypto.
"""

import re
from concurrent.futures import ThreadPoolExecutor
from api_helpers import get_currency, get_gold_price, get_stock, get_crypto, QUOTA_MSG
from line_push import reply_text as reply


def _check_quota(result, reply_token: str) -> bool:
    """Check if result is a quota-exceeded message."""
    if isinstance(result, dict) and result.get("_quota"):
        reply(reply_token, QUOTA_MSG)
        return True
    return False


def _handle_finance(reply_token: str, text: str) -> bool:
    """
    Handle finance commands: currency, gold, stock, crypto.
    Returns True if handled.
    """
    # ── 匯率 ──
    m = re.match(r"^匯率\s+(\S+)(?:\s+(\S+))?$", text)
    if m:
        from_c, to_c = m.group(1), m.group(2) or "TWD"
        result = get_currency(from_c, to_c)
        if _check_quota(result, reply_token):
            return True
        if result and result.get("rate"):
            reply(reply_token, f"💱 匯率\n\n1 {result['from']} = {result['rate']} {result['to']}")
        else:
            reply(reply_token, "匯率查詢失敗，請確認幣別代碼（如 USD JPY EUR）")
        return True

    # ── 金價 ──
    if text in ["金價", "今日金價", "黃金價格"]:
        with ThreadPoolExecutor(max_workers=2) as ex:
            f_gold = ex.submit(get_gold_price)
            f_twd = ex.submit(get_currency, "USD", "TWD")
            data = f_gold.result()
            twd = f_twd.result()
        if _check_quota(data, reply_token):
            return True
        if data and data.get("gold_usd"):
            rate = twd["rate"] if twd and twd.get("rate") and not twd.get("_quota") else 31
            gold_twd = round(float(data["gold_usd"]) * rate)
            lines = [
                f"🪙 今日金價\n",
                f"黃金：${data['gold_usd']} USD/盎司",
                f"約 NT$ {gold_twd:,} 元/盎司",
            ]
            if data.get("silver_usd"):
                lines.append(f"白銀：${data['silver_usd']} USD/盎司")
            reply(reply_token, "\n".join(lines))
        else:
            reply(reply_token, "金價查詢失敗，請稍後再試")
        return True

    # ── 股票 ──
    m = re.match(r"^股票\s+(\S+)$", text, re.IGNORECASE)
    if m:
        symbol = m.group(1).upper()
        data = get_stock(symbol)
        if _check_quota(data, reply_token):
            return True
        if data:
            arrow = "🔺" if data["change"] >= 0 else "🔻"
            sign = "+" if data["change"] >= 0 else ""
            lines = [
                f"📈 {data['symbol']} 股價\n",
                f"現價：${data['price']:,.2f}",
                f"漲跌：{arrow} {sign}{data['change']:.2f} ({data['change_pct']})",
                f"前收：${data['prev_close']:,.2f}",
                f"成交量：{data['volume']:,}",
                f"\n⏱ 資料每 5 分鐘更新",
            ]
            reply(reply_token, "\n".join(lines))
        else:
            reply(reply_token, f"找不到 {symbol} 的股價，請確認代碼（如 AAPL、TSLA、2330.TW）")
        return True

    # ── 幣價 ──
    m = re.match(r"^幣價\s+(\S+)$", text, re.IGNORECASE)
    if m:
        symbol = m.group(1)
        data = get_crypto(symbol)
        if data:
            arrow = "🔺" if data["change_24h"] >= 0 else "🔻"
            sign = "+" if data["change_24h"] >= 0 else ""
            lines = [
                f"🪙 {data['symbol'].upper()} 幣價\n",
                f"美元：${data['usd']:,.2f} USD",
                f"台幣：NT$ {data['twd']:,.0f}",
                f"24h：{arrow} {sign}{data['change_24h']}%",
                f"\n⏱ 資料每 5 分鐘更新",
            ]
            reply(reply_token, "\n".join(lines))
        else:
            reply(reply_token, f"找不到「{symbol}」的幣價，試試 BTC ETH DOGE SOL 等")
        return True

    return False
