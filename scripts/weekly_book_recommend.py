"""
每週書籍推薦 — 週六早上推送
隨機從家庭書櫃挑一本書推薦給全家
"""
import json
import os
import random
import sys

# 讓 scripts/ 目錄可被 import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from line_push import push_text_to_group

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_INDEX_PATH = os.path.join(_PROJECT_ROOT, "knowledge_base", "books", "index.json")

# 固定推薦語模板，讓每次推薦都有點變化
_INTROS = [
    "這週來讀點不一樣的！",
    "小花幫你挑了本好書 📖",
    "週末閱讀時間到！",
    "這本書放在家裡很久了，是時候翻開它了",
    "本週家庭讀書會推薦書目：",
]

_QUOTES = [
    "「讀書不是為了炫耀，而是為了在需要的時候，腦子裡有東西可用。」",
    "「你讀過的書，會變成你的一部分。」",
    "「一本好書，是作者用幾十年的人生濃縮成幾個小時送給你。」",
    "「今天不讀書，明天就只剩經驗可以依靠。」",
]


def _load_index() -> dict:
    try:
        with open(_INDEX_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        print(f"Failed to load index: {exc}")
        return {"books": []}


def _load_note(note_file: str) -> str:
    path = os.path.join(_PROJECT_ROOT, "knowledge_base", "books", note_file)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def _extract_one_liner(note_text: str) -> str:
    """從筆記中提取『一句話總結』"""
    lines = note_text.split("\n")
    capture = False
    for line in lines:
        if "一句話總結" in line:
            capture = True
            continue
        if capture and line.strip() and not line.startswith("#"):
            return line.strip().lstrip("* ").lstrip("- ")
        if capture and line.startswith("#"):
            break
    return ""


def main():
    data = _load_index()
    books = data.get("books", [])
    if not books:
        print("No books in library, skipping.")
        return

    # 優先挑待讀的書
    pending = [b for b in books if b.get("status") == "待讀"]
    if pending:
        book = random.choice(pending)
        status_note = "（這本還沒人讀過，誰要搶頭香？）"
    else:
        # 全部已讀，隨機挑一本值得重讀的
        book = random.choice(books)
        status_note = "（雖然讀過了，但好書值得再讀一次！）"

    note_text = _load_note(book.get("note_file", ""))
    one_liner = _extract_one_liner(note_text)

    lines = [
        f"📚 {random.choice(_INTROS)}",
        "",
        f"📖 《{book['title']}》",
        f"   作者：{book.get('author', '未知')}",
        f"   類別：{book.get('category', '其他')}",
    ]

    if one_liner:
        lines.extend(["", f"📝 {one_liner}"])

    lines.extend([
        "",
        f"{status_note}",
        "",
        f"💡 {random.choice(_QUOTES)}",
        "",
        "讀完後記得整理筆記放進知識庫，傳「!筆記 書名」就能查到！",
    ])

    msg = "\n".join(lines)
    print(msg)
    push_text_to_group(msg)
    print("Weekly book recommendation sent.")


if __name__ == "__main__":
    main()
