"""Family bot quiz game handler."""

import re
from line_push import reply_text as reply
from api_helpers import get_open_trivia, get_trivia, smart_translate, call_gemini

_quiz_state: dict[str, dict] = {}  # group_id -> {question, answer}


def _handle_quiz(reply_token: str, text: str, group_id: str) -> bool:
    """Handle quiz game commands."""
    if text in ["出題", "來玩問答", "問答遊戲", "出一題"]:
        trivia = get_open_trivia() or get_trivia()
        if trivia and trivia.get("question"):
            q_zh = smart_translate(trivia["question"])
            a_zh = smart_translate(trivia["answer"])
            _quiz_state[group_id] = {"question": q_zh, "answer": a_zh}
            reply(reply_token, f"🧠 問答時間！\n\n{q_zh}\n\n傳「答 你的答案」作答，傳「答案」看解答")
        else:
            qa = call_gemini("出一道適合全家的中文知識問答，格式：\n問題：xxx\n答案：xxx\n只給這兩行")
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

    m_ans = re.match(r"^答\s+(.+)$", text)
    if m_ans:
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
            reply(reply_token, "❌ 不對喔，再想想！")
        return True

    if text in ["答案", "我不知道", "放棄", "答案是什麼"]:
        if group_id in _quiz_state:
            state = _quiz_state.pop(group_id)
            reply(reply_token, f"💡 答案是：{state['answer']}")
            return True
    return False
