"""Finance Api for line-family-bot."""

import requests
import os
from datetime import datetime, timedelta
import random
import logging
logger = logging.getLogger(__name__)

from api_helpers import (
_retry_http, _cached, ALPHA_VANTAGE_KEY
)


CURRENCY_MAP = {
    "美金": "USD", "美元": "USD", "日圓": "JPY", "日幣": "JPY",
    "歐元": "EUR", "英鎊": "GBP", "韓元": "KRW", "韓幣": "KRW",
    "人民幣": "CNY", "港幣": "HKD", "澳幣": "AUD", "加幣": "CAD",
}

def get_currency(from_curr: str, to_curr: str = "TWD") -> dict | None:
    from_curr = CURRENCY_MAP.get(from_curr, from_curr.upper())
    to_curr = CURRENCY_MAP.get(to_curr, to_curr.upper())
    try:
        r = requests.get(
            f"https://open.er-api.com/v6/latest/{from_curr}",
            timeout=10,
        )
        if r.status_code != 200:
            return None
        rate = r.json().get("rates", {}).get(to_curr)
        return {"from": from_curr, "to": to_curr, "rate": round(rate, 4)} if rate else None
    except Exception:
        return None

def get_gold_price() -> dict | None:
    try:
        r = requests.get(
            "https://query1.finance.yahoo.com/v8/finance/chart/GC%3DF",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        price = r.json()["chart"]["result"][0]["meta"]["regularMarketPrice"]
        silver_r = requests.get(
            "https://query1.finance.yahoo.com/v8/finance/chart/SI%3DF",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        silver = silver_r.json()["chart"]["result"][0]["meta"]["regularMarketPrice"]
        return {"gold_usd": round(price, 2), "silver_usd": round(silver, 2)}
    except Exception:
        return None

_EXCHANGE_SUFFIX = {
    "tw": ".TW", "twse": ".TW", "otc": ".TWO",
}

def get_stock(symbol: str) -> dict | None:
    if not ALPHA_VANTAGE_KEY:
        return None
    symbol = symbol.upper().strip()
    def _fetch():
        try:
            r = requests.get(
                "https://www.alphavantage.co/query",
                params={"function": "GLOBAL_QUOTE", "symbol": symbol, "apikey": ALPHA_VANTAGE_KEY},
                timeout=12,
            )
            q = r.json().get("Global Quote", {})
            if not q or not q.get("05. price"):
                return None
            return {
                "symbol": q.get("01. symbol", symbol),
                "price": float(q["05. price"]),
                "change": float(q.get("09. change", 0)),
                "change_pct": q.get("10. change percent", "0%").strip(),
                "volume": int(q.get("06. volume", 0)),
                "prev_close": float(q.get("08. previous close", 0)),
            }
        except Exception as e:
            logger.warning("[stock] %s", e)
            return None
    return _cached(f"stock_{symbol}", 300, _fetch)

_COIN_ID_MAP = {
    "BTC": "bitcoin", "ETH": "ethereum", "USDT": "tether",
    "BNB": "binancecoin", "SOL": "solana", "XRP": "ripple",
    "DOGE": "dogecoin", "ADA": "cardano", "TRX": "tron",
    "AVAX": "avalanche-2", "DOT": "polkadot", "LINK": "chainlink",
    "比特幣": "bitcoin", "以太幣": "ethereum", "以太坊": "ethereum",
    "狗狗幣": "dogecoin", "瑞波幣": "ripple",
}

def get_crypto(symbol: str) -> dict | None:
    key = symbol.upper().strip()
    coin_id = _COIN_ID_MAP.get(key) or _COIN_ID_MAP.get(symbol) or symbol.lower()
    def _fetch():
        try:
            r = requests.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": coin_id, "vs_currencies": "usd,twd", "include_24hr_change": "true"},
                timeout=10,
            )
            data = r.json().get(coin_id)
            if not data:
                return None
            return {
                "symbol": key,
                "coin_id": coin_id,
                "usd": data.get("usd", 0),
                "twd": data.get("twd", 0),
                "change_24h": round(data.get("usd_24h_change", 0), 2),
            }
        except Exception as e:
            logger.warning("[crypto] %s", e)
            return None
    return _cached(f"crypto_{coin_id}", 300, _fetch)
