from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
import os
from datetime import datetime

# ========== 設定區 ==========
# 方法1：直接設定（僅供測試，正式環境不建議）
# CHANNEL_ACCESS_TOKEN = "你的 Channel Access Token"
# CHANNEL_SECRET = "你的 Channel Secret"

# 方法2：使用環境變數（推薦，更安全）
CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "你的預設值")
CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "你的預設值")

app = Flask(__name__)

# LINE Bot 設定
configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# ========== 路由 ==========
@app.route("/")
def home():
    return "LINE Bot is running in Deepnote! 🚀", 200

@app.route("/callback", methods=['POST'])
def callback():
    """LINE Webhook 回調函數"""
    # 取得請求標頭中的簽章
    signature = request.headers['X-Line-Signature']
    
    # 取得請求內容
    body = request.get_data(as_text=True)
    app.logger.info(f"收到訊息: {body}")
    
    # 驗證簽章並處理事件
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.error("簽章驗證失敗")
        abort(400)
    
    return 'OK', 200

# ========== 訊息處理器 ==========
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    """處理用戶傳來的文字訊息"""
    user_message = event.message.text
    user_id = event.source.user_id
    
    print(f"收到來自 {user_id} 的訊息: {user_message}")
    
    # 智慧回應邏輯
    if user_message == "你好":
        reply_text = "你好！我是你的 LINE Bot 🤖\n我可以幫你：\n- 查詢時間\n- 簡單計算\n- 聊天對話"
    
    elif user_message in ["嗨", "哈囉", "hi", "hello"]:
        reply_text = "嗨～很高興認識你！😊"
    
    elif user_message == "時間":
        now = datetime.now()
        reply_text = f"現在時間：{now.strftime('%Y-%m-%d %H:%M:%S')}"
    
    elif user_message == "日期":
        now = datetime.now()
        reply_text = f"今天是 {now.strftime('%Y年%m月%d日')}"
    
    elif user_message.startswith("計算 "):
        try:
            # 計算功能：例如「計算 10+20」
            expression = user_message.replace("計算 ", "")
            # 安全的計算（只允許數字和運算符）
            if any(op in expression for op in ['+', '-', '*', '/']):
                result = eval(expression)
                reply_text = f"{expression} = {result}"
            else:
                reply_text = "請輸入運算式，例如：計算 10+20"
        except Exception as e:
            reply_text = f"計算錯誤：{str(e)}\n請輸入正確格式，例如：計算 10+20"
    
    elif "幫助" in user_message or "help" in user_message.lower():
        reply_text = """📖 使用說明：
1. 你好 / 嗨 / hi - 打招呼
2. 時間 - 顯示目前時間
3. 日期 - 顯示今天日期
4. 計算 10+20 - 簡單計算
5. 其他訊息 - 我會回覆你"""
    
    else:
        reply_text = f"你說：{user_message}\n\n輸入「幫助」查看使用說明 📖"
    
    # 回覆訊息
    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_text)]
                )
            )
        print(f"已回覆: {reply_text}")
    except Exception as e:
        print(f"發送訊息失敗: {e}")

# ========== 錯誤處理 ==========
@app.errorhandler(404)
def not_found(error):
    return "404 - 頁面不存在", 404

@app.errorhandler(500)
def internal_error(error):
    return "500 - 伺服器錯誤", 500

# ========== 主程式 ==========
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True)   # fix indent
