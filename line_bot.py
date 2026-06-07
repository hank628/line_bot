from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
import os

CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")

# 檢查環境變數是否設定
if not CHANNEL_ACCESS_TOKEN:
    print("❌ 錯誤：LINE_CHANNEL_ACCESS_TOKEN 未設定")
if not CHANNEL_SECRET:
    print("❌ 錯誤：LINE_CHANNEL_SECRET 未設定")

app = Flask(__name__)
configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

@app.route("/")
def home():
    return "LINE Bot is running!", 200

@app.route("/test")
def test():
    return "Test page is working!", 200

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    print(f"收到請求: {body[:100]}...")
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("❌ 簽驗證錯誤")
        abort(400)
    return 'OK', 200

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_msg = event.message.text
    print(f"收到訊息: {user_msg}")
    reply_text = f"你說：{user_msg}"
    
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )
    print(f"已回覆: {reply_text}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"啟動服務在 port {port}")
    app.run(host="0.0.0.0", port=port)
