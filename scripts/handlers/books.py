"""
家庭書櫃知識庫 handler
支援指令：
  !找書 [關鍵字]     — 搜尋書名或作者
  !筆記 [書名]       — 顯示某本書的筆記摘要
  !書單              — 列出家庭書單
  !推薦書 [主題]     — 根據主題推薦家中書籍
  !新增書 [書名] [作者] [類別] — 添加新書到索引
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

# 知識庫根目錄（從 scripts/handlers/ 往上兩層到專案根目錄）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_KB_DIR = os.path.join(_PROJECT_ROOT, "knowledge_base")
_BOOKS_DIR = os.path.join(_KB_DIR, "books")
_INDEX_PATH = os.path.join(_BOOKS_DIR, "index.json")


def _load_index() -> Dict[str, Any]:
    """載入書單索引"""
    try:
        with open(_INDEX_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("Failed to load book index: %s", exc)
        return {"books": []}


def _save_index(data: Dict[str, Any]) -> bool:
    """儲存書單索引"""
    try:
        with open(_INDEX_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as exc:
        logger.warning("Failed to save book index: %s", exc)
        return False


def _load_note(note_file: str) -> str:
    """載入某本書的筆記內容"""
    path = os.path.join(_BOOKS_DIR, note_file)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as exc:
        logger.warning("Failed to load note %s: %s", note_file, exc)
        return ""


def _extract_summary(note_text: str, max_chars: int = 800) -> str:
    """從 md 筆記中提取摘要（一句話總結 + 核心觀點前幾點）"""
    lines = note_text.split("\n")
    summary_lines = []
    in_summary = False
    for line in lines:
        # 抓「一句話總結」
        if "一句話總結" in line:
            in_summary = True
            continue
        if in_summary and line.strip() and not line.startswith("#"):
            summary_lines.append(line.strip().lstrip("* ").lstrip("- "))
            if len("\n".join(summary_lines)) > 200:
                break
        if in_summary and line.startswith("#") and "核心觀點" in line:
            break

    result = "\n".join(summary_lines)
    if len(result) > max_chars:
        result = result[:max_chars] + "..."
    return result or "（尚無摘要）"


def _search_books(query: str) -> List[Dict[str, Any]]:
    """根據關鍵字搜尋書籍"""
    data = _load_index()
    query_lower = query.lower()
    results = []
    for book in data.get("books", []):
        text = f"{book.get('title','')} {book.get('author','')} {book.get('category','')} {' '.join(book.get('tags',[]))}"
        if query_lower in text.lower():
            results.append(book)
    return results


def _find_book_by_title(title_query: str) -> Dict[str, Any] | None:
    """模糊匹配書名"""
    data = _load_index()
    books = data.get("books", [])
    # 先試精確匹配
    for b in books:
        if b.get("title", "").lower() == title_query.lower():
            return b
    # 再試包含匹配
    for b in books:
        if title_query.lower() in b.get("title", "").lower():
            return b
    # 再試 tags
    for b in books:
        if any(title_query.lower() in t.lower() for t in b.get("tags", [])):
            return b
    return None


# ─── Handler Functions ──────────────────────────────────────

def handle_find_book(reply_token: str, text: str) -> bool:
    """!找書 [關鍵字]"""
    m = re.match(r"^!找書\s+(.+)", text)
    if not m:
        return False
    query = m.group(1).strip()
    results = _search_books(query)
    if not results:
        reply(reply_token, f"📚 找不到「{query}」相關的書。試試其他關鍵字，或傳「!書單」查看全部。")
        return True
    lines = [f"📚 找到 {len(results)} 本相關書籍：\n"]
    for b in results:
        status_emoji = "✅" if b.get("status") == "已筆記" else "📖"
        lines.append(f"{status_emoji} 《{b['title']}》{b.get('author','')}")
        lines.append(f"   類別：{b.get('category','')} | 擁有者：{b.get('owner','')} | 狀態：{b.get('status','')}")
        if b.get("tags"):
            lines.append(f"   標籤：{' '.join(b['tags'])}")
        lines.append("")
    reply(reply_token, "\n".join(lines)[:1900])
    return True


def handle_book_note(reply_token: str, text: str) -> bool:
    """!筆記 [書名]"""
    m = re.match(r"^!筆記\s+(.+)", text)
    if not m:
        return False
    title_query = m.group(1).strip()
    book = _find_book_by_title(title_query)
    if not book:
        reply(reply_token, f"📚 找不到「{title_query}」。傳「!書單」查看我們家有什麼書。")
        return True

    note_text = _load_note(book.get("note_file", ""))
    if not note_text:
        reply(reply_token, f"📖 《{book['title']}》還沒有筆記。快讀完整理一份吧！")
        return True

    summary = _extract_summary(note_text, max_chars=900)
    lines = [
        f"📖 《{book['title']}》— {book.get('author','')}",
        f"類別：{book.get('category','')} | 擁有者：{book.get('owner','')}",
        "",
        f"📝 筆記摘要：",
        summary,
    ]
    reply(reply_token, "\n".join(lines)[:1900])
    return True


def handle_book_list(reply_token: str, text: str) -> bool:
    """!書單 — 列出家庭書單"""
    if text != "!書單":
        return False
    data = _load_index()
    books = data.get("books", [])
    if not books:
        reply(reply_token, "📚 家庭書櫃還是空的。傳「!新增書 書名 作者 類別」開始建檔吧！")
        return True

    # 統計
    total = len(books)
    noted = sum(1 for b in books if b.get("status") == "已筆記")
    categories = {}
    for b in books:
        cat = b.get("category", "其他")
        categories[cat] = categories.get(cat, 0) + 1

    lines = [f"📚 家庭書櫃（共 {total} 本，已筆記 {noted} 本）\n"]

    # 按類別分組
    for cat in sorted(categories.keys()):
        lines.append(f"【{cat}】")
        cat_books = [b for b in books if b.get("category") == cat]
        for b in cat_books:
            status = "✅" if b.get("status") == "已筆記" else "📖"
            owner = b.get("owner", "")
            lines.append(f"  {status} 《{b['title']}》{b.get('author','')} ({owner})")
        lines.append("")

    lines.append("💡 傳「!找書 關鍵字」搜尋 | 「!筆記 書名」看摘要")
    reply(reply_token, "\n".join(lines)[:1900])
    return True


def handle_recommend_book(reply_token: str, text: str) -> bool:
    """!推薦書 [主題]"""
    m = re.match(r"^!推薦書\s+(.+)", text)
    if not m:
        return False
    topic = m.group(1).strip()
    data = _load_index()
    books = data.get("books", [])

    # 搜尋 tags + category + title
    scored = []
    for b in books:
        score = 0
        text_all = f"{b.get('title','')} {b.get('category','')} {' '.join(b.get('tags',[]))}"
        if topic.lower() in text_all.lower():
            score += 10
        for tag in b.get("tags", []):
            if topic.lower() in tag.lower():
                score += 5
        if score > 0:
            scored.append((score, b))

    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored:
        reply(reply_token, f"📚 沒找到「{topic}」相關的書。我們家目前的書單：\n傳「!書單」查看。")
        return True

    lines = [f"📚 為你推薦「{topic}」相關書籍：\n"]
    for score, b in scored[:5]:
        status = "✅" if b.get("status") == "已筆記" else "📖"
        lines.append(f"{status} 《{b['title']}》— {b.get('author','')}")
        lines.append(f"   類別：{b.get('category','')} | 標籤：{' '.join(b.get('tags',[]))}")
        lines.append("")
    reply(reply_token, "\n".join(lines)[:1900])
    return True


def handle_add_book(reply_token: str, text: str) -> bool:
    """!新增書 [書名] [作者] [類別]"""
    m = re.match(r"^!新增書\s+(.+)", text)
    if not m:
        return False
    parts = m.group(1).strip().split()
    if len(parts) < 2:
        reply(reply_token, "📚 格式：!新增書 書名 作者 [類別]\n例：!新增書 原子習慣 James Clear 自我成長")
        return True

    title = parts[0]
    author = parts[1] if len(parts) > 1 else ""
    category = parts[2] if len(parts) > 2 else "其他"

    data = _load_index()
    books = data.get("books", [])

    # 檢查是否已存在
    for b in books:
        if b.get("title", "").lower() == title.lower():
            reply(reply_token, f"📚 《{title}》已經在書櫃裡了。傳「!筆記 {title}」查看。")
            return True

    # 產生安全檔名
    safe_name = re.sub(r'[^\w\u4e00-\u9fff]', '_', title)[:30]
    note_file = f"{safe_name}.md"

    new_book = {
        "id": safe_name,
        "title": title,
        "author": author,
        "category": category,
        "owner": "",
        "status": "待讀",
        "note_file": note_file,
        "tags": [],
        "added_date": "2026-06-04"
    }
    books.append(new_book)
    data["books"] = books

    if _save_index(data):
        # 同時建立空白筆記模板
        note_path = os.path.join(_BOOKS_DIR, note_file)
        if not os.path.exists(note_path):
            template = f"""# 《{title}》

**作者：** {author}
**類別：** {category}
**閱讀者：**
**閱讀日期：**

---

## 一句話總結

（讀完後填寫）

---

## 核心觀點

1.
2.
3.

---

## 金句摘錄

>

---

## 實用行動清單

- [ ]
- [ ]
- [ ]

---

## 個人心得

（留白）

---

## 推薦給誰

"""
            try:
                with open(note_path, "w", encoding="utf-8") as f:
                    f.write(template)
            except Exception as exc:
                logger.warning("Failed to create note template: %s", exc)

        reply(reply_token, f"📚 《{title}》已加入家庭書櫃！\n類別：{category} | 作者：{author}\n\n✏️ 空白筆記模板已建立，讀完後記得整理成 md 檔放回 knowledge_base/books/ 喔！")
    else:
        reply(reply_token, "❌ 新增失敗，請稍後再試")
    return True


# 給 webhook.py import 用的統一入口
def handle_book_command(reply_token: str, text: str) -> bool:
    """
    統一處理所有書櫃指令。
    回傳 True 表示已處理。
    """
    handlers = [
        handle_find_book,
        handle_book_note,
        handle_book_list,
        handle_recommend_book,
        handle_add_book,
    ]
    for h in handlers:
        if h(reply_token, text):
            return True
    return False
