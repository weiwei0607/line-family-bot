"""
Link scraper + shared link library.
Auto-extracts URLs from text, fetches titles, saves to Sheets.
"""

import re
import requests
from sheets import _get_service, _get_sheet_id, _ensure_tab, TW_TZ
from datetime import datetime

_TAB = "連結庫"


def _today():
    return datetime.now(TW_TZ).strftime("%Y-%m-%d")


def _now():
    return datetime.now(TW_TZ).strftime("%H:%M")


def _append_row(row):
    svc = _get_service()
    if not svc:
        return False
    _ensure_tab(_TAB)
    try:
        svc.spreadsheets().values().append(
            spreadsheetId=_get_sheet_id(),
            range=f"{_TAB}!A1",
            valueInputOption="USER_ENTERED",
            body={"values": [row]},
        ).execute()
        return True
    except Exception as e:
        print(f"[Links] Append failed: {e}")
        return False


def _read_all():
    svc = _get_service()
    if not svc:
        return []
    _ensure_tab(_TAB)
    try:
        result = svc.spreadsheets().values().get(
            spreadsheetId=_get_sheet_id(), range=f"{_TAB}!A2:F1000"
        ).execute()
        return result.get("values", [])
    except Exception:
        return []


def extract_urls(text: str) -> list[str]:
    pattern = r'https?://[^\s\u3000<>"{}|\\^`\[\]]+'
    found = re.findall(pattern, text)
    return list(dict.fromkeys(found))


def fetch_title(url: str, timeout: int = 8) -> tuple[str, str]:
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        }
        r = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        r.raise_for_status()
        html = r.text
        title = url
        m = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
        if m:
            import html as _html
            title = _html.unescape(m.group(1)).strip().replace("\n", " ").replace("\r", "")
            if len(title) > 200:
                title = title[:200]
        snippet = ""
        md = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)', html, re.IGNORECASE)
        if not md:
            md = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']description["\']', html, re.IGNORECASE)
        if md:
            snippet = md.group(1).strip()
        else:
            mp = re.search(r'<p[^>]*>(.*?)</p>', html, re.IGNORECASE | re.DOTALL)
            if mp:
                import html as _html
                snippet = re.sub(r'<[^>]+>', '', mp.group(1))
                snippet = _html.unescape(snippet).strip().replace("\n", " ")
                snippet = snippet[:200]
        return title, snippet
    except Exception as e:
        print(f"[Links] Fetch failed for {url}: {e}")
        return url, ""


def save_link(member: str, url: str, title: str = "", snippet: str = "") -> bool:
    if not title:
        title, snippet = fetch_title(url)
    return _append_row([_today(), _now(), member, title, url, snippet])


def list_links(limit: int = 10) -> list[dict]:
    rows = _read_all()
    links = []
    for r in reversed(rows):
        if len(r) >= 5:
            links.append({
                "date": r[0] if len(r) > 0 else "",
                "time": r[1] if len(r) > 1 else "",
                "member": r[2] if len(r) > 2 else "",
                "title": r[3] if len(r) > 3 else "",
                "url": r[4] if len(r) > 4 else "",
                "snippet": r[5] if len(r) > 5 else "",
            })
        if len(links) >= limit:
            break
    return links


def search_links(keyword: str) -> list[dict]:
    rows = _read_all()
    kw = keyword.lower()
    results = []
    for r in reversed(rows):
        if len(r) >= 5:
            title = r[3] if len(r) > 3 else ""
            url = r[4] if len(r) > 4 else ""
            snippet = r[5] if len(r) > 5 else ""
            if kw in title.lower() or kw in url.lower() or kw in snippet.lower():
                results.append({
                    "date": r[0] if len(r) > 0 else "",
                    "time": r[1] if len(r) > 1 else "",
                    "member": r[2] if len(r) > 2 else "",
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                })
    return results


# ── webhook handlers ─────────────────────────────

def handle_link_command(reply_token: str, text: str, member: str, reply_fn) -> bool:
    """Handle link library commands. Returns True if handled."""
    urls = extract_urls(text)
    if urls and not text.startswith(("記事", "筆記", "找記事", "刪除記事", "連結庫", "找連結")):
        saved = []
        for url in urls:
            if save_link(member or "家人", url):
                saved.append(url)
        if saved:
            reply_fn(reply_token, f"🔗 已儲存 {len(saved)} 個連結到連結庫")
            return True

    if text == "連結庫":
        links = list_links(10)
        if not links:
            reply_fn(reply_token, "🔗 連結庫還沒有內容\n用法：直接貼網址到群組，我會自動存")
            return True
        lines = ["🔗 連結庫（最近10則）："]
        for li in links:
            snippet = f" — {li['snippet'][:20]}" if li.get("snippet") else ""
            lines.append(f"• {li['date']} {li['title']}{snippet}")
        lines.append("\n🔍 找連結 關鍵字")
        reply_fn(reply_token, "\n".join(lines))
        return True

    m = re.match(r"^(?:找連結|搜尋連結)\s+(.+)", text)
    if m:
        kw = m.group(1)
        results = search_links(kw)
        if not results:
            reply_fn(reply_token, f"🔍 找不到「{kw}」相關連結")
            return True
        lines = [f"🔍 「{kw}」搜尋結果："]
        for r in results[:10]:
            lines.append(f"• {r['title']}\n  {r['url']}")
        reply_fn(reply_token, "\n".join(lines))
        return True

    return False
