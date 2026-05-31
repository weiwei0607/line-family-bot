"""
LINE 家庭群機器人 webhook
"""

import os
import re
import json
import requests
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, TextMessage,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from api_helpers import (
    format_weather_block, get_advice, get_horoscope, get_fun_fact,
    search_recipes_by_ingredients, get_nutrition, get_movie_by_genre,
    RAPIDAPI_KEY,
)

from sheets import (
    bg, get_members, get_chores, complete_chore, add_chore,
    get_weekly_points, format_weekly_summary, register_member,
    batch_log_points, get_shopping_list, add_shopping, complete_shopping,
    add_expense, get_expenses, get_member_weekly_breakdown,
    get_member_weekly_chore_points, WEEKLY_CAPS,
    add_declutter, get_declutter_list, complete_declutter,
    add_income, get_declutter_income, cancel_last_record,
    pay_fine, get_outstanding_fines,
)

app = Flask(__name__)

_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
_secret = os.environ.get("LINE_CHANNEL_SECRET", "")
configuration = Configuration(access_token=_token)
handler = WebhookHandler(_secret)
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
POINTS_THRESHOLD = int(os.environ.get("POINTS_THRESHOLD", "5"))

_quiz_state: dict[str, dict] = {}  # group_id -> {question, answer}

# ─── 工具函數 ─────────────────────────────────

def reply(reply_token: str, text: str):
    with ApiClient(configuration) as api_client:
        MessagingApi(api_client).reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=text[:4900])],
            )
        )

def call_gemini(prompt: str) -> str:
    if not GEMINI_KEY:
        return "（需要設定 GEMINI_API_KEY）"
    try:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/"
            f"models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
        )
        resp = requests.post(
            url,
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=20,
        )
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        return f"AI 回答失敗：{e}"

# ─── 指令處理 ─────────────────────────────────

def handle_chores(reply_token: str, member: str, text: str):
    """處理家事相關指令"""
    m = re.match(r"^(完成|做了|做好了|完成了)\s*(.+)", text)
    if m:
        chore_name = m.group(2).strip()
        result = complete_chore(chore_name, member or "不知道誰")
        if result and result.get("capped"):
            reply(reply_token,
                  f"⚠️ {member or '你'} 本週「{result['name']}」已達上限 {result['cap']} 點，不再計分喔！")
        elif result:
            pts = result["points"]
            pts_str = f"{pts:.2f}".rstrip('0').rstrip('.')
            summary = format_weekly_summary()
            reply(reply_token,
                  f"✅ {member or '你'} 完成了「{result['name']}」！獲得 {pts_str} 點 🎉\n\n{summary}")
        else:
            reply(reply_token,
                  f"找不到「{chore_name}」這個家事耶，確認一下名稱是否正確？\n"
                  f"輸入「家事清單」看看所有家事")
        return True

    if text in ["家事清單", "家事", "待完成", "還有什麼家事"]:
        chores = get_chores()
        if not chores:
            reply(reply_token, "🎉 家事清單是空的！")
        else:
            lines = ["📋 家事清單：\n"]
            for c in chores:
                cap = WEEKLY_CAPS.get(c['name'])
                cap_str = f"（上限{cap}點/週）" if cap else ""
                lines.append(f"• {c['name']}  {c['points']}點{cap_str}")
            reply(reply_token, "\n".join(lines))
        return True

    m = re.match(r"^新增家事\s+(.+?)(\s+(\d+)點?)?$", text)
    if m:
        name = m.group(1).strip()
        pts = int(m.group(3)) if m.group(3) else 1
        bg(add_chore, name, pts)
        reply(reply_token, f"✅ 新增家事「{name}」（{pts}點），大家加油！")
        return True

    return False


def handle_points(reply_token: str, member: str, text: str):
    """查詢點數"""
    if text in ["點數", "查點數", "點數排行", "積分", "本週點數"]:
        pts = get_weekly_points()
        members = get_members()
        lines = ["🏆 本週家事點數：\n"]
        for m in members:
            p = pts.get(m, 0)
            p_str = f"{p:.2f}".rstrip('0').rstrip('.')
            warn = " ⚠️ 未達標" if p < POINTS_THRESHOLD else " ✅"
            lines.append(f"{m}：{p_str} 點{warn}")
        lines.append(f"\n（目標：每週 {POINTS_THRESHOLD} 點以上）")
        reply(reply_token, "\n".join(lines))
        return True

    if text in ["我的點數", "我的紀錄", "我做了什麼", "我的家事"]:
        if not member:
            reply(reply_token, "還不知道你是誰，先傳「我是＿＿」讓我記住你 😊")
            return True
        breakdown = get_member_weekly_breakdown(member)
        total = sum(d["points"] for d in breakdown)
        total_str = f"{total:.2f}".rstrip('0').rstrip('.')
        if not breakdown:
            reply(reply_token, f"{member} 本週還沒有記錄，快去做家事！💪")
        else:
            lines = [f"📋 {member} 本週家事：\n"]
            for d in breakdown:
                p_str = f"{d['points']:.2f}".rstrip('0').rstrip('.')
                lines.append(f"• {d['name']}  {p_str}點")
            lines.append(f"\n合計：{total_str} 點")
            status = "✅ 已達標" if total >= POINTS_THRESHOLD else f"⚠️ 距目標還差 {POINTS_THRESHOLD - total:.2f}".rstrip('0').rstrip('.') + " 點"
            lines.append(status)
            reply(reply_token, "\n".join(lines))
        return True

    # 取消記錄
    m = re.match(r"^取消記錄\s*(.*)$", text)
    if m or text in ["取消上筆", "取消記錄"]:
        if not member:
            reply(reply_token, "還不知道你是誰，先傳「我是＿＿」讓我記住你 😊")
            return True
        chore_name = m.group(1).strip() if m and m.group(1).strip() else None
        result = cancel_last_record(member, chore_name)
        if result:
            p_str = f"{result['points']:.2f}".rstrip('0').rstrip('.')
            reply(reply_token, f"✅ 已取消「{result['name']}」的 {p_str} 點記錄")
        else:
            tip = f"「{chore_name}」的" if chore_name else ""
            reply(reply_token, f"找不到{tip}記錄，沒有東西可以取消")
        return True

    return False


def handle_shopping(reply_token: str, member: str, text: str):
    """購物清單指令"""
    m = re.match(r"^(加購物|要買|買|購物加)\s+(.+)", text)
    if m:
        item = m.group(2).strip()
        bg(add_shopping, item, member or "")
        reply(reply_token, f"🛒 已加入購物清單：{item}")
        return True

    m = re.match(r"^(買好了|已買|買到了|買了)\s+(.+)", text)
    if m:
        item = m.group(2).strip()
        ok = complete_shopping(item, member or "")
        if ok:
            reply(reply_token, f"✅ 已標記「{item}」已購買 🛒")
        else:
            reply(reply_token, f"找不到「{item}」在購物清單裡喔")
        return True

    if text in ["購物清單", "要買什麼"]:
        items = get_shopping_list(only_pending=True)
        if not items:
            reply(reply_token, "🛒 購物清單是空的！")
        else:
            lines = ["🛒 待購物清單：\n"]
            for it in items:
                lines.append(f"• {it['name']}（{it['added_by']} 加的）")
            reply(reply_token, "\n".join(lines))
        return True

    return False


def handle_accounting(reply_token: str, member: str, text: str):
    """家庭記帳"""
    m = re.match(r"^記帳\s+(\d+)\s+(.+?)(?:\s+(.+))?$", text)
    if m:
        amount = int(m.group(1))
        part2 = m.group(2).strip()
        part3 = m.group(3).strip() if m.group(3) else ""
        if part3:
            category, desc = part2, part3
        else:
            category, desc = "雜費", part2
        bg(add_expense, amount, category, desc, member or "")
        reply(reply_token,
              f"💰 已記帳：{category} - {desc}，{amount} 元\n（{member or ''}）")
        return True

    if text in ["帳", "帳目", "今日帳", "本週帳", "查帳"]:
        days = 1 if "今日" in text else 7
        exps = get_expenses(days=days)
        if not exps:
            reply(reply_token, f"最近 {days} 天沒有記帳紀錄")
        else:
            total = sum(e["amount"] for e in exps)
            label = "今日" if days == 1 else "最近7天"
            lines = [f"💰 {label}支出（共 {total} 元）：\n"]
            for e in exps[-10:]:
                lines.append(f"• {e['date']} {e['category']} {e['desc']} {e['amount']}元（{e['by']}）")
            reply(reply_token, "\n".join(lines))
        return True

    return False


def handle_fine(reply_token: str, member: str, text: str) -> bool:
    """罰款與欠款指令"""
    m = re.match(r"^繳罰款\s+(\d+)$", text)
    if m:
        if not member:
            reply(reply_token, "還不知道你是誰，先傳「我是＿＿」😊")
            return True
        amount = int(m.group(1))
        pay_fine(member, amount)
        balances = get_outstanding_fines(member=member)
        remaining = balances.get(member, 0)
        if remaining <= 0:
            reply(reply_token, f"✅ {member} 已繳 {amount} 元，欠款清零！小本本乾淨了 🎉")
        else:
            reply(reply_token, f"✅ {member} 已繳 {amount} 元，還欠 {remaining} 元")
        return True

    if text in ["欠款", "欠款清單", "小本本"]:
        balances = get_outstanding_fines()
        if not balances:
            reply(reply_token, "📒 小本本是空的，大家都沒有欠款 🎉")
        else:
            lines = ["📒 欠款小本本：\n"]
            for m_name, total in balances.items():
                if total > 0:
                    lines.append(f"  {m_name}：欠 {total} 元")
                elif total < 0:
                    lines.append(f"  {m_name}：多繳了 {-total} 元")
            lines.append("\n投幣後傳「繳罰款 金額」登記")
            reply(reply_token, "\n".join(lines))
        return True

    return False


def handle_declutter(reply_token: str, member: str, text: str) -> bool:
    """斷捨離指令"""
    # 加入待定區
    m = re.match(r"^斷捨離\s+(.+)", text)
    if m and text not in ["斷捨離清單", "斷捨離收入"]:
        item = m.group(1).strip()
        bg(add_declutter, item, member or "")
        reply(reply_token, f"🗂️ 「{item}」已加入待定區\n確定要處理時傳「丟了 {item}」或「賣了 {item} 金額」")
        return True

    # 查待定清單
    if text == "斷捨離清單":
        items = get_declutter_list(only_pending=True)
        if not items:
            reply(reply_token, "🎉 待定區是空的，家裡很清爽！")
        else:
            lines = [f"🗂️ 斷捨離待定區（{len(items)} 項）：\n"]
            for it in items:
                lines.append(f"• {it['name']}（{it['added_by']} 加的）")
            lines.append("\n傳「丟了 物品名」或「賣了 物品名 金額」來處理")
            reply(reply_token, "\n".join(lines))
        return True

    # 丟棄
    m = re.match(r"^丟了\s+(.+)", text)
    if m:
        item = m.group(1).strip()
        result = complete_declutter(item, "丟棄", member or "")
        if result:
            reply(reply_token, f"🗑️ 「{item}」已丟棄！斷捨離成功 ✨")
        else:
            reply(reply_token, f"找不到「{item}」在待定區，先傳「斷捨離 {item}」加進去")
        return True

    # 賣出（帶金額）
    m = re.match(r"^賣了\s+(.+?)\s+(\d+)$", text)
    if m:
        item = m.group(1).strip()
        amount = int(m.group(2))
        result = complete_declutter(item, "賣出", member or "", amount)
        if result:
            bg(add_income, amount, f"賣掉：{item}", member or "")
            reply(reply_token, f"💰 「{item}」賣出 {amount} 元！\n已自動記入家庭帳本（斷捨離收入）✨")
        else:
            reply(reply_token, f"找不到「{item}」在待定區，先傳「斷捨離 {item}」加進去")
        return True

    # 賣出（沒帶金額）
    m = re.match(r"^賣了\s+(.+)", text)
    if m:
        item = m.group(1).strip()
        reply(reply_token, f"「{item}」賣了多少錢？請傳完整格式：\n「賣了 {item} 金額」")
        return True

    # 查斷捨離收入
    if text == "斷捨離收入":
        records = get_declutter_income()
        if not records:
            reply(reply_token, "目前還沒有斷捨離收入記錄")
        else:
            total = sum(r["amount"] for r in records)
            lines = [f"💰 斷捨離收入（共 {total} 元）：\n"]
            for r in records[-10:]:
                lines.append(f"• {r['date']} {r['desc']} {r['amount']}元（{r['by']}）")
            reply(reply_token, "\n".join(lines))
        return True

    return False


def handle_fun(reply_token: str, source, text: str) -> bool:
    """天氣、吃什麼、星座、問答、食譜、熱量、電影、冷知識、人生建議"""

    # 天氣
    if text in ["天氣", "今天天氣", "天氣如何", "外面天氣"]:
        reply(reply_token, "🌡 今日天氣\n\n" + format_weather_block())
        return True

    # 今天吃什麼
    if text in ["今天吃什麼", "吃什麼", "晚餐吃什麼", "午餐吃什麼"]:
        suggestion = call_gemini(
            "隨機推薦一道台灣家常料理，給出菜名、簡單食材（3-5樣）和一句做法說明。格式：\n"
            "🍽 [菜名]\n食材：xxx\n做法：xxx"
        )
        reply(reply_token, suggestion)
        return True

    # 星座運勢
    m = re.match(r"^(牡羊|金牛|雙子|巨蟹|獅子|處女|天秤|天蠍|射手|摩羯|水瓶|雙魚)座?運勢?$", text)
    if m or text in ["星座"]:
        if text == "星座":
            reply(reply_token, "請傳「[星座]運勢」\n例：天蠍座運勢、射手運勢")
            return True
        sign_zh = m.group(1)
        data = get_horoscope(sign_zh)
        if data:
            desc = call_gemini(f"把這段英文星座運勢翻譯成繁體中文，簡潔2-3句：{data['description']}")
            lines = [
                f"✨ {data['sign']} 今日運勢\n",
                desc,
                f"\n心情：{data['mood']}　幸運色：{data['color']}",
                f"幸運數字：{data['lucky_number']}　配對：{data['compatibility']}座",
            ]
            reply(reply_token, "\n".join(lines))
        else:
            reply(reply_token, "星座資料取得失敗，待會再試試")
        return True

    # 問答遊戲 — 出題
    if text in ["出題", "來玩問答", "問答遊戲", "出一題"]:
        group_id = getattr(source, "group_id", None) or getattr(source, "room_id", "default")
        qa = call_gemini(
            "出一道適合全家一起玩的中文知識問答題（生活常識、台灣文化、有趣冷知識皆可），格式固定：\n"
            "問題：xxx\n答案：xxx\n只給這兩行，不要其他說明"
        )
        question, answer = "", ""
        for line in qa.strip().splitlines():
            if line.startswith("問題："):
                question = line[3:].strip()
            elif line.startswith("答案："):
                answer = line[3:].strip()
        if question and answer:
            _quiz_state[group_id] = {"question": question, "answer": answer}
            reply(reply_token, f"🧠 問答時間！\n\n{question}\n\n傳「答 你的答案」作答，傳「答案」看解答")
        else:
            reply(reply_token, "出題失敗，再試一次！")
        return True

    # 問答遊戲 — 作答
    m_ans = re.match(r"^答\s+(.+)$", text)
    if m_ans:
        group_id = getattr(source, "group_id", None) or getattr(source, "room_id", "default")
        if group_id not in _quiz_state:
            reply(reply_token, "目前沒有進行中的題目，傳「出題」開始！")
            return True
        state = _quiz_state[group_id]
        user_ans = m_ans.group(1).strip().lower()
        correct = state["answer"].lower()
        if correct in user_ans or user_ans in correct:
            del _quiz_state[group_id]
            reply(reply_token, f"🎉 答對了！答案是：{state['answer']}")
        else:
            reply(reply_token, f"❌ 不對喔，再想想！")
        return True

    # 問答遊戲 — 看答案
    if text in ["答案", "我不知道", "放棄", "答案是什麼"]:
        group_id = getattr(source, "group_id", None) or getattr(source, "room_id", "default")
        if group_id in _quiz_state:
            state = _quiz_state.pop(group_id)
            reply(reply_token, f"答案是：{state['answer']} 💡")
            return True

    # 食譜搜尋（需要 RAPIDAPI_KEY）
    m = re.match(r"^食譜\s+(.+)$", text)
    if m:
        if not RAPIDAPI_KEY:
            reply(reply_token, "食譜搜尋需要設定 RAPIDAPI_KEY")
            return True
        ingredients = m.group(1).strip()
        results = search_recipes_by_ingredients(ingredients)
        if results:
            lines = [f"🍳 含「{ingredients}」的食譜：\n"]
            for r in results[:3]:
                lines.append(f"• {r.get('title', '')}（缺：{len(r.get('missedIngredients', []))} 樣食材）")
            reply(reply_token, "\n".join(lines))
        else:
            reply(reply_token, "找不到相關食譜，換個食材試試")
        return True

    # 熱量查詢（需要 RAPIDAPI_KEY）
    m = re.match(r"^熱量\s+(.+)$", text)
    if m:
        if not RAPIDAPI_KEY:
            reply(reply_token, "熱量查詢需要設定 RAPIDAPI_KEY")
            return True
        food = m.group(1).strip()
        items = get_nutrition(food)
        if items:
            lines = [f"🔥 熱量查詢：{food}\n"]
            for it in items[:3]:
                lines.append(
                    f"• {it.get('name', '')}（{it.get('serving_size_g', '')}g）：{round(it.get('calories', 0))} 卡"
                    f"　蛋白質 {round(it.get('protein_g', 0))}g　脂肪 {round(it.get('fat_total_g', 0))}g"
                )
            reply(reply_token, "\n".join(lines))
        else:
            reply(reply_token, "查不到這個食物的熱量，試試英文名稱")
        return True

    # 電影推薦
    if text in ["推薦電影", "今晚看什麼", "電影推薦"]:
        movie = call_gemini(
            "推薦一部適合全家一起看的電影，給出片名（中英文）、年份、一句推薦理由。格式：\n"
            "🎬 [片名]\n年份：xxx\n推薦理由：xxx"
        )
        reply(reply_token, movie)
        return True

    m = re.match(r"^推薦電影\s+(.+)$", text)
    if m:
        genre = m.group(1).strip()
        movie = call_gemini(
            f"推薦一部{genre}類型的電影，給出片名（中英文）、年份、一句推薦理由。格式：\n"
            "🎬 [片名]\n年份：xxx\n推薦理由：xxx"
        )
        reply(reply_token, movie)
        return True

    # 冷知識
    if text in ["冷知識", "今日冷知識", "告訴我一件事"]:
        fact_en = get_fun_fact()
        if fact_en:
            fact_zh = call_gemini(f"把這個冷知識翻成繁體中文，保持趣味性，只給翻譯結果：{fact_en}")
            reply(reply_token, f"🤓 冷知識\n\n{fact_zh}")
        else:
            reply(reply_token, "今天沒有冷知識，改天再問")
        return True

    # 人生建議
    if text in ["給我建議", "人生建議", "今日建議", "金玉良言"]:
        advice_en = get_advice()
        if advice_en:
            translated = call_gemini(f"把這句英文建議翻譯成繁體中文，只給翻譯結果：{advice_en}")
            reply(reply_token, f"💡 {translated}\n\n（{advice_en}）")
        else:
            reply(reply_token, "今天沒有建議，就靠自己吧！")
        return True

    return False


def handle_ai_mention(reply_token: str, text: str):
    """@機器人 問問題"""
    m = re.match(r"^@?(?:機器人|家管|bot|助理|小花)\s+(.+)", text, re.IGNORECASE)
    if m:
        question = m.group(1).strip()
        answer = call_gemini(
            f"你是一個溫暖實用的家庭助理，用繁體中文回答，簡潔不囉嗦。\n\n問題：{question}"
        )
        reply(reply_token, answer)
        return True
    return False


def handle_admin(reply_token: str, event: MessageEvent, text: str):
    """管理指令"""
    if text in ["群組id", "群組ID", "groupid", "群id"]:
        source = event.source
        gid = getattr(source, "group_id", None) or getattr(source, "room_id", None) or "不是群組訊息"
        reply(reply_token, f"群組 ID：{gid}")
        return True

    m = re.match(r"^(?:我是|叫我|我叫)\s*(.+)", text)
    if m:
        name = m.group(1).strip()
        user_id = getattr(event.source, "user_id", "")
        approved = get_members()
        if name not in approved:
            names_str = "、".join(approved) if approved else "（尚未設定成員）"
            reply(reply_token, f"「{name}」不在成員名單裡喔！\n"
                               f"目前成員：{names_str}\n"
                               f"請用正確的家人稱呼 😊")
            return True
        if user_id and name:
            bg(register_member, user_id, name)
            _member_cache[user_id] = name
            reply(reply_token, f"好的！以後叫你「{name}」😊\n"
                               f"完成家事時傳「完成 家事名稱」就會記在你名下囉")
        return True

    return False


def handle_batch_log(reply_token: str, member: str, text: str) -> bool:
    """批量登錄：第一行「完成」，後續每行一個家事"""
    lines = [l.strip() for l in text.strip().splitlines()]
    if len(lines) < 2:
        return False

    first = lines[0]
    if first not in ["完成", "完成了"] and not re.match(r'^\d+[/／]\d+\s*完成', first):
        return False

    chore_lines = lines[1:]

    # 最後一行只有匹配到已登記成員才視為名字
    members_list = get_members()
    who = member or ""
    last = chore_lines[-1] if chore_lines else ""
    if last and not re.search(r'\d', last):
        matched = next((m for m in members_list if m in last or last in m), None)
        if matched:
            who = matched
            chore_lines = chore_lines[:-1]

    # 解析家事行
    chore_pattern = re.compile(r'^(.+?)(\d+\.?\d*)$')
    chores_sheet = None
    chores: list[tuple[str, float]] = []
    for line in chore_lines:
        if not line:
            continue
        m = chore_pattern.match(line)
        if m:
            chores.append((m.group(1).strip(), float(m.group(2))))
        else:
            if chores_sheet is None:
                chores_sheet = get_chores()
            matched_chore = next(
                (c for c in chores_sheet if line in c["name"] or c["name"] in line),
                None,
            )
            pts = matched_chore["points"] if matched_chore else 1.0
            name = matched_chore["name"] if matched_chore else line
            chores.append((name, pts))

    if not chores:
        reply(reply_token, "沒有找到任何家事，請確認格式：\n完成\n家事名稱\n家事名稱")
        return True

    # 上限檢查（跳過超過上限的項目）
    who = who or member or "家人"
    valid_chores: list[tuple[str, float]] = []
    capped_names: list[str] = []
    for name, pts in chores:
        cap = WEEKLY_CAPS.get(name)
        if cap is not None:
            already = get_member_weekly_chore_points(who, name)
            remaining = cap - already
            if remaining <= 0:
                capped_names.append(name)
                continue
            pts = min(pts, remaining)
        valid_chores.append((name, pts))

    if not valid_chores:
        cap_str = "、".join(capped_names)
        reply(reply_token, f"⚠️ {who} 本週「{cap_str}」已達點數上限，沒有新增記錄。")
        return True

    try:
        batch_log_points(who, valid_chores)
        summary = format_weekly_summary()
    except Exception as e:
        reply(reply_token, f"記錄失敗：{e}")
        return True

    total = sum(p for _, p in valid_chores)
    total_str = f"{total:.2f}".rstrip('0').rstrip('.')
    lines_out = [f"✅ {name} +{f'{pts:.2f}'.rstrip('0').rstrip('.')}" for name, pts in valid_chores]

    msg = f"📋 {who} 的家事記錄\n" + "\n".join(lines_out) + f"\n\n共 +{total_str} 點 🎉"
    if capped_names:
        msg += f"\n⚠️ 已達上限略過：{'、'.join(capped_names)}"
    msg += f"\n\n{summary}"
    reply(reply_token, msg)
    return True


def handle_help(reply_token: str, text: str):
    if text in ["說明", "幫助", "功能", "help", "指令", "指令清單", "清單"]:
        reply(reply_token, """🏠 家管助理指令清單

【家事】
• 完成 [家事名稱]
• 完成（換行列多項家事）— 批量記錄
• 家事清單 — 查所有家事
• 新增家事 [名稱] [點數]

【點數】
• 查點數 — 全員本週排行
• 我的點數 — 自己本週明細
• 取消記錄 [家事名稱] — 取消最近一筆

【購物】
• 買 [項目] — 加入購物清單
• 買好了 [項目] — 標記已購
• 購物清單 — 查看清單

【記帳】
• 記帳 [金額] [說明] — 記錄支出
• 今日帳 / 查帳 — 查今日/7天支出

【罰款】
• 繳罰款 [金額] — 投幣後登記
• 欠款 / 小本本 — 查累積欠款

【斷捨離】
• 斷捨離 [物品] — 加入待定區
• 丟了 [物品] — 標記丟棄
• 賣了 [物品] [金額] — 賣出並記帳
• 斷捨離清單 — 查待定區
• 斷捨離收入 — 查賣出總收入

【生活小工具】
• 天氣 — 今日天氣 + 空氣品質
• 今天吃什麼 — AI 推薦家常料理
• [星座]運勢 — 例：天蠍座運勢
• 出題 — 家庭問答遊戲（答 xxx 作答）
• 食譜 [食材] — 依食材找食譜 *
• 熱量 [食物] — 查食物卡路里 *
• 推薦電影 [類型] — AI 推薦電影
• 冷知識 — 隨機有趣知識
• 給我建議 — 隨機人生建議
（* 需啟用 RAPIDAPI_KEY）

【其他】
• 我是 [名字] — 登記身分
• 助理 [問題] / 小花 [問題] — AI 問答

目標：每週 5 點，少一點罰 50 元 🎯""")
        return True
    return False

# ─── Webhook 入口 ─────────────────────────────

@app.route("/")
def health():
    return "OK", 200

@app.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event: MessageEvent):
    if not hasattr(event, "reply_token") or not event.reply_token:
        return

    text = event.message.text.strip()
    reply_token = event.reply_token

    member = ""
    if hasattr(event, "source") and hasattr(event.source, "user_id"):
        member = _resolve_member(event.source.user_id)

    if (
        handle_admin(reply_token, event, text) or
        handle_batch_log(reply_token, member, text) or
        handle_help(reply_token, text) or
        handle_chores(reply_token, member, text) or
        handle_points(reply_token, member, text) or
        handle_shopping(reply_token, member, text) or
        handle_accounting(reply_token, member, text) or
        handle_fine(reply_token, member, text) or
        handle_declutter(reply_token, member, text) or
        handle_fun(reply_token, event.source, text) or
        handle_ai_mention(reply_token, text)
    ):
        return

    # 被 @ 提及時 AI 回答
    if hasattr(event, "message") and hasattr(event.message, "mention"):
        if event.message.mention:
            answer = call_gemini(
                f"你是一個溫暖實用的家庭助理，用繁體中文回答，簡潔不囉嗦。\n\n問題：{text}"
            )
            reply(reply_token, answer)


# user_id → 成員名對照
_member_cache: dict[str, str] = {}
_cache_ts: float = 0

def _resolve_member(user_id: str) -> str:
    import time
    global _cache_ts
    now = time.time()
    if now - _cache_ts > 600:
        _refresh_member_cache()
        _cache_ts = now
    return _member_cache.get(user_id, "")

def _refresh_member_cache():
    try:
        from sheets import _read
        rows = _read("設定", "A2:B30")
        for r in rows:
            if len(r) >= 2 and r[0].strip() and r[1].strip():
                _member_cache[r[1].strip()] = r[0].strip()
    except Exception:
        pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
