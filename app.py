from flask import Flask, request, abort
import os
import time
import json
import math
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

# ===== 載入 HR KB（在啟動時讀一次）=====
KB_PATH = os.path.join(os.path.dirname(__file__), "hr_kb.json")
with open(KB_PATH, "r", encoding="utf-8") as f:
    KB = json.load(f)

KB_META = KB.get("meta", {})
KB_ITEMS = KB.get("items", [])

def cosine_sim(a, b):
    # a,b: list[float]
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

def retrieve_chunks(query: str, top_k: int = 5):
    # 1) query embedding
    q_emb = client.embeddings.create(
        model="text-embedding-3-small",
        input=query
    ).data[0].embedding

    # 2) compute similarity
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

    # 3) 組成引用文字（含頁碼）
    refs = []
    for s, it in top:
        refs.append({
            "score": float(s),
            "page": it.get("page"),
            "text": it.get("text", "").strip()
        })
    return refs

# ===== callback Webhook =====
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

    # 取出 KB meta（你要的「根據 202509 的 HR-103-04 版本出勤管理辦法」）
    policy_month = KB_META.get("policy_month", "未知月份")
    policy_code = KB_META.get("policy_code", "未知版次")
    policy_name = KB_META.get("policy_name", "未知辦法")

    prefix = f"📌 根據 {policy_month} 的 {policy_code} 版本《{policy_name}》內容回覆：\n"

    # ===== RAG：找最相關條文段落 =====
    refs = retrieve_chunks(user_text, top_k=5)

    # 可加一道「相關性門檻」：太不相關就直接請洽人資
    # 你可先用 0.25~0.35 之間測試（依文件品質調整）
    best_score = refs[0]["score"] if refs else 0.0
    if best_score < 0.25:
        gpt_answer = "此問題在目前管理辦法引用內容中找不到明確依據，請洽人資專員。"
    else:
        # 把引用段落塞進 prompt（非常重要）
        context_block = "\n\n".join(
            [f"[頁 {r['page']}] {r['text']}" for r in refs]
        )

        prompt = f"""
你是 microSHIFT 公司的 HR 人資助理。
你**只能**依據「引用內容」回答，不得使用一般常識或網路資訊補充。
如果引用內容不足以回答，請回覆：「此問題在目前管理辦法引用內容中找不到明確依據，請洽人資專員。」

【引用內容】
{context_block}

【員工問題】
{user_text}

【回答要求】
- 用員工問題的語言回覆
- 清楚、簡短、條列式優先
- 如有條文條件或例外，要明確寫出
"""

        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "你是公司內部 HR Bot（嚴格引用文件回答）"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
        )
        gpt_answer = resp.choices[0].message.content.strip()

    # 組合回覆
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
