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
import random
import requests

# ========== 設定區 ==========
CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "你的預設值")
CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "你的預設值")

app = Flask(__name__)

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# ========== 英文單字庫 ==========
vocabulary = {
    "apple": "蘋果 🍎",
    "book": "書 📚",
    "cat": "貓 🐱",
    "dog": "狗 🐶",
    "eat": "吃 🍽️",
    "fish": "魚 🐟",
    "good": "好的 ✅",
    "happy": "快樂的 😊",
    "ice": "冰 🧊",
    "joy": "喜悅 🎉",
}

# ========== 取得天氣（免費 API） ==========
def get_weather(city="Taipei"):
    """從 OpenWeatherMap 取得天氣"""
    try:
        # 免費 API，不需要註冊也能用（有限制）
        url = f"https://wttr.in/{city}?format=%C+%t&lang=zh"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            weather_text = response.text.strip()
            return f"🌤️ {city} 天氣：{weather_text}"
        else:
            return f"🌤️ {city}：多雲時晴，25°C（即時資訊取得失敗）"
    except:
        return f"🌤️ {city}：多雲時晴，24-28°C（模擬資料）"

# ========== 路由 ==========
@app.route("/")
def home():
    return "LINE Bot is running! 🚀", 200

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info(f"收到訊息: {body}")
    
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.error("簽章驗證失敗")
        abort(400)
    
    return 'OK', 200

# ========== 訊息處理器 ==========
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_message = event.message.text.strip().lower()
    user_id = event.source.user_id
    
    print(f"收到來自 {user_id} 的訊息: {user_message}")
    
    # ========== 回應邏輯 ==========
    
    # 1. 查英文單字
    if user_message.startswith("查 "):
        word = user_message.replace("查 ", "").strip()
        if word in vocabulary:
            reply_text = f"📖 {word} = {vocabulary[word]}"
        else:
            reply_text = f"❌ 找不到「{word}」\n\n📚 目前有：{', '.join(vocabulary.keys())}"
    
    # 2. 隨機單字測驗
    elif user_message == "單字":
        word, meaning = random.choice(list(vocabulary.items()))
        reply_text = f"📚 單字小測驗\n\n請問「{word}」是什麼意思？\n\n💡 提示：輸入「查 {word}」看答案"
    
    # 3. 天氣查詢
    elif user_message == "天氣":
        reply_text = get_weather("Taipei")
    
    elif user_message.startswith("天氣 "):
        city = user_message.replace("天氣 ", "").strip()
        reply_text = get_weather(city)
    
    # 4. 台北天氣
    elif user_message == "台北天氣":
        reply_text = get_weather("Taipei")
    
    # 5. 幫助選單
    elif user_message in ["幫助", "help", "說明", "選單"]:
        reply_text = """📖 **使用說明**

🔤 **英文單字**
• 查 [單字] - 查詢單字意思，例如：查 apple
• 單字 - 隨機單字測驗

🌤️ **天氣查詢**
• 天氣 - 查詢台北天氣
• 天氣 [城市] - 查詢其他城市，例如：天氣 Taipei

✨ **其他**
• 幫助 - 顯示此選單
• 時間 - 顯示目前時間"""

    # 6. 顯示時間
    elif user_message == "時間":
        now = datetime.now()
        reply_text = f"⏰ 現在時間：{now.strftime('%Y-%m-%d %H:%M:%S')}"
    
    # 7. 打招呼
    elif user_message in ["你好", "嗨", "哈囉", "hi", "hello"]:
        reply_text = "嗨！我是你的小幫手 🤖\n我可以幫你：\n• 查英文單字\n• 查天氣\n\n輸入「幫助」查看完整功能"
    
    # 8. 預設回覆
    else:
        reply_text = f"你說：「{user_message}」\n\n💡 試試看：\n• 查 apple\n• 天氣\n• 幫助"
    
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
        print(f"✅ 已回覆")
    except Exception as e:
        print(f"❌ 發送失敗: {e}")

# ========== 主程式 ==========
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True)
