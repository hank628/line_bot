from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
import os
import sqlite3

CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")

app = Flask(__name__)

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# 初始化資料庫（最簡化）
def init_db():
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS test (id INTEGER PRIMARY KEY, name TEXT)''')
    c.execute("INSERT OR IGNORE INTO test (id, name) VALUES (1, 'test')")
    conn.commit()
    conn.close()
    print("✅ 資料庫初始化完成")

init_db()

@app.route("/")
def home():
    return "HANK EduMentor is running!", 200

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK', 200

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    msg = event.message.text
    reply_text = f"你說：{msg}\n\n資料庫測試："
    
    # 測試資料庫
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("SELECT name FROM test WHERE id = 1")
    result = c.fetchone()
    conn.close()
    
    if result:
        reply_text += f" 成功讀取資料：{result[0]}"
    else:
        reply_text += " 讀取失敗"
    
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
