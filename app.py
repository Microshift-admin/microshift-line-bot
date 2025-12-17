from flask import Flask, request, abort
import os
import time
import json
import math
from collections import Counter
from openai import OpenAI

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

# ===== HR Bot 設定 =====
HR_INTRO_TEXT = (
    "你好，我是【微轉人資AI助手】🤖\n\n"
    "你可以直接輸入人資相關問題，例如：\n"
    "・病假規則是什麼？\n"
    "・加班費如何計算？\n"
    "・特休規定有哪些？\n"
)
INTRO_COOLDOWN_SECONDS = 60 * 60 * 12  # 12 小時
last_seen = {}

# ===== 建立 Flask / OpenAI / LINE 物件 =====
app = Flask(__name__)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))

# ===== 讀取 HR KB Index（啟動時讀一次）=====
KB_INDEX_PATH = os.path.join(os.path.dirname(__file__), "hr_kb_index.json")
with open(KB_INDEX_PATH, "r", encoding="utf-8") as f:
    KB = json.load(f)

KB_META = KB.get("meta", {})
KB_ITEMS = KB.get("items", [])

# ===== 向量相似度 =====
def cosine_sim(a, b):
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0 or nb == 0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))

def retrieve_chunks(query: str, top_k: int = 6):
    q_emb = client.embeddings.create(
        model="text-embedding-3-small",
        input=query
    ).data[0].embedding

    scored = []
    for it in KB_ITEMS:
        emb = it.get("embedding")
        txt = it.get("text", "")
        if not emb or not txt:
            continue
        s = cosine_sim(q_emb, emb)
        scored.append((s, it))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:top_k]

    refs = []
    for s, it in top:
        refs.append({
            "score": float(s),
            "policy_month": it.get("policy_month", "未知月份"),
            "policy_code": it.get("policy_code", "未知版次"),
            "policy_name": it.get("policy_name", "未知辦法"),
            "source_filename": it.get("source_filename", ""),
            "chunk_id": it.get("chunk_id", 0),
            "text": (it.get("text", "") or "").strip()
        })
    return refs

def pick_best_policy(refs):
    # 用 top refs 的「多數決」選最像哪一份文件；平手就取最高分那份
    if not refs:
        return ("未知月份", "未知版次", "未知辦法")
    keys = [(r["policy_month"], r["policy_code"], r["policy_name"]) for r in refs]
    c = Counter(keys)
    best_key, _ = c.most_common(1)[0]
    return best_key

# ===== callback Webhook 接收 =====
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK"

# ===== handler：HR + RAG + GPT =====
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_text = event.message.text.strip()
    user_id = event.source.user_id

    now = time.time()
    last = last_seen.get(user_id)
    should_show_intro = (last is None) or ((now - last) > INTRO_COOLDOWN_SECONDS)
    last_seen[user_id] = now

    # 1) RAG 找引用段落
    refs = retrieve_chunks(user_text, top_k=6)
    best_score = refs[0]["score"] if refs else 0.0

    # 門檻：太低就直接請洽人資（避免亂掰/泛回答）
    THRESHOLD = 0.28

    if best_score < THRESHOLD:
        reply_core = "此問題在目前規章引用內容中找不到明確依據，請洽人資專員。"
        # prefix 仍可顯示（但這裡不顯示也可以，你若想不顯示我也能改）
        reply_text = f"{HR_INTRO_TEXT}\n{reply_core}" if should_show_intro else reply_core

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text)
        )
        return

    policy_month, policy_code, policy_name = pick_best_policy(refs)
    prefix = f"📌 根據 {policy_month} 的 {policy_code} 版本《{policy_name}》內容回覆：\n\n"

    # 2) 把引用內容塞給 GPT（強制只能依引用回答）
    context_block = "\n\n".join(
        [f"[{r['policy_code']}#{r['chunk_id']}] {r['text']}" for r in refs]
    )

    prompt = f"""
你是 microSHIFT 公司的 HR 人資助理。
你**只能根據**下方【引用內容】回答，禁止使用一般常識、網路資訊或推測補充。
如果【引用內容】不足以回答，請回覆：「此問題在目前規章引用內容中找不到明確依據，請洽人資專員。」

【引用內容】
{context_block}

【員工問題】
{user_text}

【回答要求】
- 用繁體中文
- 專業、清楚
- 優先用條列
- 若有條件/例外，需講清楚
"""

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "你是公司內部 HR Bot（只能依引用內容回答）"},
            {"role": "user", "content": prompt}
        ],
        temperature=0.1
    )

    gpt_answer = resp.choices[0].message.content.strip()

    # 3) 組合成給員工看的回覆
    if should_show_intro:
        reply_text = f"{HR_INTRO_TEXT}\n{prefix}{gpt_answer}"
    else:
        reply_text = f"{prefix}{gpt_answer}"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
