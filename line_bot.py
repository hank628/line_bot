from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, TextMessage, FlexMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, PostbackEvent
import os
from datetime import datetime
import random
import requests

CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")

app = Flask(__name__)

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# ========== 單字庫 ==========
vocabulary = {
    "apple": "蘋果 🍎",
    "book": "書 📚",
    "cat": "貓 🐱",
    "dog": "狗 🐶",
    "sun": "太陽 ☀️",
    "moon": "月亮 🌙"
}

# ========== 待辦事項 ==========
todos = {}

# ========== 天氣 ==========
def get_weather(city="Taipei"):
    try:
        url = f"https://wttr.in/{city}?format=%C+%t&lang=zh"
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            return f"🌤️ {city}：{r.text.strip()}"
    except:
        pass
    return f"🌤️ {city}：多雲時晴，24-28°C"

# ========== 主選單 ==========
def create_main_menu():
    return FlexMessage(
        alt_text="功能選單",
        contents={
            "type": "bubble",
            "header": {"type": "box", "layout": "vertical", "contents": [
                {"type": "text", "text": "🤖 功能選單", "weight": "bold", "size": "xl", "align": "center"}
            ]},
            "body": {"type": "box", "layout": "vertical", "spacing": "md", "contents": [
                {"type": "button", "style": "primary", "color": "#1E88E5", "action": {"type": "postback", "label": "🌤️ 天氣", "data": "weather", "displayText": "天氣"}},
                {"type": "button", "style": "primary", "color": "#43A047", "action": {"type": "postback", "label": "📚 英文", "data": "vocab", "displayText": "英文"}},
                {"type": "button", "style": "primary", "color": "#FB8C00", "action": {"type": "postback", "label": "🎓 助理", "data": "assistant", "displayText": "教學助理"}},
                {"type": "button", "style": "primary", "color": "#8E24AA", "action": {"type": "postback", "label": "✅ 待辦", "data": "todo", "displayText": "待辦事項"}}
            ]}
        }
    )

# ========== 路由 ==========
@app.route("/")
def home():
    return "LINE Bot is running!", 200

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK', 200

# ========== 按鈕點擊 ==========
@handler.add(PostbackEvent)
def handle_postback(event):
    data = event.postback.data
    user_id = event.source.user_id
    
    if data == "weather":
        reply = TextMessage(text=get_weather("Taipei"))
    elif data == "vocab":
        word, meaning = random.choice(list(vocabulary.items()))
        reply = TextMessage(text=f"📖 {word} = {meaning}")
    elif data == "assistant":
        reply = TextMessage(text="🎓 教學助理上線！\n\n試試看：\n• 查 apple\n• 計算 1+2\n• 天氣")
    elif data == "todo":
        items = todos.get(user_id, [])
        if items:
            text = "✅ 待辦清單：\n" + "\n".join([f"{i+1}. {t}" for i, t in enumerate(items[:5])])
        else:
            text = "📋 目前沒有待辦事項\n\n輸入「新增 買牛奶」來新增"
        reply = TextMessage(text=text)
    else:
        reply = create_main_menu()
    
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(reply_token=event.reply_token, messages=[reply])
        )

# ========== 文字訊息 ==========
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    msg = event.message.text.strip()
    msg_lower = msg.lower()
    user_id = event.source.user_id
    
    # 主選單
    if msg_lower in ["選單", "功能", "幫助", "menu"]:
        reply = create_main_menu()
    
    # 查單字
    elif msg_lower.startswith("查 "):
        word = msg_lower[3:]
        if word in vocabulary:
            reply = TextMessage(text=f"📖 {word} = {vocabulary[word]}")
        else:
            reply = TextMessage(text=f"❌ 查無「{word}」\n試試：apple, book, cat, dog")
    
    # 隨機單字
    elif msg_lower == "單字":
        word, meaning = random.choice(list(vocabulary.items()))
        reply = TextMessage(text=f"📖 {word} = {meaning}")
    
    # 天氣
    elif "天氣" in msg_lower:
        city = "Taipei"
        if "台北" in msg:
            city = "Taipei"
        elif "台中" in msg:
            city = "Taichung"
        elif "高雄" in msg:
            city = "Kaohsiung"
        reply = TextMessage(text=get_weather(city))
    
    # 新增待辦
    elif msg_lower.startswith("新增 "):
        task = msg[3:]
        if user_id not in todos:
            todos[user_id] = []
        todos[user_id].append(task)
        reply = TextMessage(text=f"✅ 已新增：{task}\n目前共 {len(todos[user_id])} 項")
    
    # 顯示待辦
    elif msg_lower in ["待辦", "待辦事項", "todo"]:
        items = todos.get(user_id, [])
        if items:
            text = "✅ 待辦清單：\n" + "\n".join([f"{i+1}. {t}" for i, t in enumerate(items[:5])])
        else:
            text = "📋 沒有待辦事項\n\n輸入「新增 買牛奶」來新增"
        reply = TextMessage(text=text)
    
    # 完成全部
    elif msg_lower in ["完成全部", "清空待辦"]:
        todos[user_id] = []
        reply = TextMessage(text="✅ 已清空所有待辦事項！")
    
    # 時間
    elif "時間" in msg_lower or "幾點" in msg_lower:
        now = datetime.now()
        reply = TextMessage(text=f"⏰ {now.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 計算
    elif msg_lower.startswith("計算 "):
        try:
            expr = msg_lower[3:]
            result = eval(expr)
            reply = TextMessage(text=f"{expr} = {result}")
        except:
            reply = TextMessage(text="計算錯誤，請用：計算 1+2")
    
    # 預設
    else:
        reply = TextMessage(text=f"你說了：「{msg}」\n\n💡 輸入「幫助」看功能選單")
    
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(reply_token=event.reply_token, messages=[reply])
        )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True)
