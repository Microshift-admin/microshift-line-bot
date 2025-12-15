# ===== import 區域 =====
from flask import Flask, request, abort
import os
import time
from openai import OpenAI
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
# ===== import 區域結束 =====

# ===== HR Bot 設定 =====
HR_INTRO_TEXT = (
    "你好, 我是微轉人資AI助手 🤖\n\n"
        "你可以直接輸入問題, 例如: \n\n"
        "病假規則是什麼? \n"
        "加班費如何計算? \n"
        "特休規定有哪些? \n\n"
)
INTRO_COOLDOWN_SECONDS = 60 * 60 * 12  #12小時才出現一次intro
# 暫存每個 LINE 使用者的最後互動時間
last_seen = {}
# ===== HR Bot 設定結束 =====

# ===== 建立Flask/OpenAI/LINE物件 =====
app = Flask(__name__)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))
# ===== 建立Flask/OpenAI/LINE物件 結束=====

# ===== callback Webhook接收 =====
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK"
# ===== callback Webhook接收 結束=====

# ===== handler HR+GPT邏輯=====
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_text = event.message.text.strip()
    user_id = event.source.user_id #LIND用戶唯一ID

    now = time.time()
    last = last_seen.get(user_id)

    should_show_intro = (last is None) or ((now - last) > INTRO_COOLDOWN_SECONDS)
    last_seen[user_id] = now
    
#給GPT的規則(只管專業回答)
    prompt = f"""
       你是 microshift 公司的 HR 人資助理。
請用專業、清楚、簡短的方式回答員工問題。
如果問題與人資無關，請回覆「此問題非規範範圍，請洽人資專員」。

員工問題：
{user_text}
"""

        response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "你是公司內部 HR Bot"},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2
    )

    gpt_answer = response.choices[0].message.content.strip()

    # 🔹 組合成給員工看的回覆
        if should_show_intro:
        reply_text = f"{HR_INTRO_TEXT}\n📖【HR AI助手 回覆】\n\n{gpt_answer}"
    else:
        reply_text = f"HR AI助手 回覆\n\n{gpt_answer}"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
