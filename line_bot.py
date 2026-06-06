from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, TextMessage, FlexMessage,
    QuickReply, QuickReplyItem, MessageAction,
    PostbackAction, URIAction
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, PostbackEvent
import os
from datetime import datetime
import random
import requests
import json

# ========== 設定區 ==========
CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "你的預設值")
CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "你的預設值")

app = Flask(__name__)

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# ========== 待辦事項儲存（暫時用記憶體，重啟會清空） ==========
todos = {}

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
    "sun": "太陽 ☀️",
    "moon": "月亮 🌙",
}

# ========== 天氣函數 ==========
def get_weather(city="Taipei"):
    try:
        url = f"https://wttr.in/{city}?format=%C+%t&lang=zh"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            weather_text = response.text.strip()
            return f"🌤️ {city} 天氣：{weather_text}"
        else:
            return f"🌤️ {city}：多雲時晴，24-28°C"
    except:
        return f"🌤️ {city}：多雲時晴，24-28°C"

# ========== 建立主要選單（Flex Message） ==========
def create_main_menu():
    """建立四個按鈕的主選單"""
    flex_content = {
        "type": "bubble",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "🤖 功能選單",
                    "weight": "bold",
                    "size": "xl",
                    "align": "center"
                },
                {
                    "type": "text",
                    "text": "請點擊下方按鈕",
                    "size": "sm",
                    "color": "#aaaaaa",
                    "align": "center"
                }
            ]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "height": "sm",
                    "action": {
                        "type": "postback",
                        "label": "🌤️ 天氣預報",
                        "data": "action=weather",
                        "displayText": "天氣預報"
                    },
                    "color": "#1E88E5"
                },
                {
                    "type": "button",
                    "style": "primary",
                    "height": "sm",
                    "action": {
                        "type": "postback",
                        "label": "📚 英文單字",
                        "data": "action=vocab",
                        "displayText": "英文單字"
                    },
                    "color": "#43A047"
                },
                {
                    "type": "button",
                    "style": "primary",
                    "height": "sm",
                    "action": {
                        "type": "postback",
                        "label": "🎓 教學助理",
                        "data": "action=assistant",
                        "displayText": "教學助理"
                    },
                    "color": "#FB8C00"
                },
                {
                    "type": "button",
                    "style": "primary",
                    "height": "sm",
                    "action": {
                        "type": "postback",
                        "label": "✅ 待辦事項",
                        "data": "action=todo",
                        "displayText": "待辦事項"
                    },
                    "color": "#8E24AA"
                }
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "點擊按鈕開始使用",
                    "size": "xs",
                    "color": "#aaaaaa",
                    "align": "center"
                }
            ]
        }
    }
    
    return FlexMessage(
        alt_text="功能選單",
        contents=flex_content
    )

# ========== 天氣選單 ==========
def create_weather_menu():
    flex_content = {
        "type": "bubble",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "🌤️ 天氣預報",
                    "weight": "bold",
                    "size": "xl",
                    "align": "center"
                }
            ]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "contents": [
                {
                    "type": "button",
                    "style": "secondary",
                    "height": "sm",
                    "action": {
                        "type": "postback",
                        "label": "📍 台北",
                        "data": "action=weather&city=Taipei",
                        "displayText": "台北天氣"
                    }
                },
                {
                    "type": "button",
                    "style": "secondary",
                    "height": "sm",
                    "action": {
                        "type": "postback",
                        "label": "📍 台中",
                        "data": "action=weather&city=Taichung",
                        "displayText": "台中午天氣"
                    }
                },
                {
                    "type": "button",
                    "style": "secondary",
                    "height": "sm",
                    "action": {
                        "type": "postback",
                        "label": "📍 高雄",
                        "data": "action=weather&city=Kaohsiung",
                        "displayText": "高雄天氣"
                    }
                },
                {
                    "type": "button",
                    "style": "secondary",
                    "height": "sm",
                    "action": {
                        "type": "postback",
                        "label": "📍 東京",
                        "data": "action=weather&city=Tokyo",
                        "displayText": "東京天氣"
                    }
                },
                {
                    "type": "button",
                    "style": "link",
                    "height": "sm",
                    "action": {
                        "type": "postback",
                        "label": "◀ 返回主選單",
                        "data": "action=menu",
                        "displayText": "主選單"
                    },
                    "color": "#aaaaaa"
                }
            ]
        }
    }
    
    return FlexMessage(
        alt_text="天氣預報選單",
        contents=flex_content
    )

# ========== 英文單字選單 ==========
def create_vocab_menu():
    flex_content = {
        "type": "bubble",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "📚 英文單字",
                    "weight": "bold",
                    "size": "xl",
                    "align": "center"
                }
            ]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "contents": [
                {
                    "type": "button",
                    "style": "secondary",
                    "height": "sm",
                    "action": {
                        "type": "postback",
                        "label": "📖 隨機單字",
                        "data": "action=random_word",
                        "displayText": "隨機單字"
                    }
                },
                {
                    "type": "button",
                    "style": "secondary",
                    "height": "sm",
                    "action": {
                        "type": "postback",
                        "label": "📋 單字本",
                        "data": "action=word_list",
                        "displayText": "單字本"
                    }
                },
                {
                    "type": "separator",
                    "margin": "md"
                },
                {
                    "type": "text",
                    "text": "🔍 查單字：輸入「查 apple」",
                    "size": "xs",
                    "color": "#aaaaaa",
                    "align": "center"
                },
                {
                    "type": "button",
                    "style": "link",
                    "height": "sm",
                    "action": {
                        "type": "postback",
                        "label": "◀ 返回主選單",
                        "data": "action=menu",
                        "displayText": "主選單"
                    },
                    "color": "#aaaaaa"
                }
            ]
        }
    }
    
    return FlexMessage(
        alt_text="英文單字選單",
        contents=flex_content
    )

# ========== 待辦事項選單 ==========
def create_todo_menu(user_id):
    todos_list = todos.get(user_id, [])
    
    todo_items = []
    if todos_list:
        for i, task in enumerate(todos_list[:5], 1):
            todo_items.append({
                "type": "text",
                "text": f"{i}. {task}",
                "size": "sm",
                "wrap": True
            })
    else:
        todo_items.append({
            "type": "text",
            "text": "目前沒有待辦事項",
            "size": "sm",
            "color": "#aaaaaa",
            "align": "center"
        })
    
    flex_content = {
        "type": "bubble",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "✅ 待辦事項",
                    "weight": "bold",
                    "size": "xl",
                    "align": "center"
                }
            ]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "button",
                    "style": "secondary",
                    "height": "sm",
                    "action": {
                        "type": "postback",
                        "label": "➕ 新增事項",
                        "data": "action=todo_add",
                        "displayText": "新增待辦事項"
                    }
                },
                {
                    "type": "separator",
                    "margin": "md"
                },
                {
                    "type": "text",
                    "text": "📋 待辦清單",
                    "weight": "bold",
                    "size": "sm",
                    "margin": "md"
                }
            ] + todo_items + [
                {
                    "type": "button",
                    "style": "link",
                    "height": "sm",
                    "action": {
                        "type": "postback",
                        "label": "🗑️ 完成全部",
                        "data": "action=todo_clear",
                        "displayText": "完成全部"
                    },
                    "color": "#ef5350",
                    "margin": "md"
                },
                {
                    "type": "button",
                    "style": "link",
                    "height": "sm",
                    "action": {
                        "type": "postback",
                        "label": "◀ 返回主選單",
                        "data": "action=menu",
                        "displayText": "主選單"
                    },
                    "color": "#aaaaaa",
                    "margin": "md"
                }
            ]
        }
    }
    
    return FlexMessage(
        alt_text="待辦事項",
        contents=flex_content
    )

# ========== 教學助理 ==========
def create_assistant_reply(question):
    if not question or question == "教學助理":
        return """🎓 **教學助理**

我可以幫你：
• 解釋英文單字
• 簡單數學計算
• 基本知識問答

請直接輸入你的問題～"""
    
    # 簡單的問答邏輯
    q_lower = question.lower()
    
    if "數學" in q_lower or "計算" in q_lower:
        return "📐 請輸入「計算 1+2」來算數學～"
    elif "英文" in q_lower:
        return "📖 輸入「查 apple」查單字，或「單字」隨機測驗"
    elif any(word in q_lower for word in ["你好", "嗨", "hello"]):
        return "嗨！有什麼可以幫你的嗎？😊"
    else:
        return f"🤔 關於「{question}」\n\n💡 試試看：\n• 查 [單字]\n• 計算 1+2\n• 天氣"

# ========== 路由 ==========
@app.route("/")
def home():
    return "LINE Bot is running! 🚀", 200

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    
    return 'OK', 200

# ========== 處理按鈕點擊 ==========
@handler.add(PostbackEvent)
def handle_postback(event):
    data = event.postback.data
    user_id = event.source.user_id
    
    print(f"收到按鈕點擊: {data} from {user_id}")
    
    # 解析 data
    params = {}
    for item in data.split("&"):
        if "=" in item:
            key, val = item.split("=", 1)
            params[key] = val
    
    action = params.get("action", "")
    
    if action == "menu":
        reply_message = create_main_menu()
    
    elif action == "weather":
        city = params.get("city", "Taipei")
        weather_info = get_weather(city)
        reply_message = TextMessage(text=weather_info)
    
    elif action == "vocab":
        reply_message = create_vocab_menu()
    
    elif action == "random_word":
        word, meaning = random.choice(list(vocabulary.items()))
        reply_message = TextMessage(text=f"📖 {word} = {meaning}")
    
    elif action == "word_list":
        word_list = "\n".join([f"• {w} = {m}" for w, m in list(vocabulary.items())[:10]])
        reply_message = TextMessage(text=f"📚 單字本\n{word_list}")
    
    elif action == "assistant":
        reply_message = TextMessage(text=create_assistant_reply("教學助理"))
    
    elif action == "todo":
        reply_message = create_todo_menu(user_id)
    
    elif action == "todo_add":
        reply_message = TextMessage(text="請輸入你要新增的待辦事項\n\n例如：買牛奶")
    
    elif action == "todo_clear":
        if user_id in todos:
            todos[user_id] = []
        reply_message = TextMessage(text="✅ 已清空所有待辦事項！")
    
    else:
        reply_message = create_main_menu()
    
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[reply_message]
            )
        )

# ========== 處理文字訊息 ==========
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_message = event.message.text.strip()
    user_message_lower = user_message.lower()
    user_id = event.source.user_id
    
    print(f"收到來自 {user_id} 的訊息: {user_message}")
    
    # 待辦事項：等待新增
    if user_message_lower.startswith("新增 ") or user_message_lower.startswith("加 "):
        task = user_message.replace("新增 ", "").replace("加 ", "").strip()
        if user_id not in todos:
            todos[user_id] = []
        todos[user_id].append(task)
        reply_text = f"✅ 已新增：{task}\n\n目前有 {len(todos[user_id])} 項待辦"
    
    # 查單字
    elif user_message_lower.startswith("查 "):
        word = user_message_lower.replace("查 ", "").strip()
        if word in vocabulary:
            reply_text = f"📖 {word} = {vocabulary[word]}"
        else:
            reply_text = f"❌ 查無「{word}」\n\n試試：apple, book, cat, dog..."
    
    # 隨機單字
    elif user_message_lower in ["單字", "隨機單字"]:
        word, meaning = random.choice(list(vocabulary.items()))
        reply_text = f"📖 {word} = {meaning}"
    
    # 天氣
    elif user_message_lower in ["天氣", "天氣預報"]:
        reply_message = create_weather_menu()
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[reply_message]
                )
            )
        return
    
    # 教學助理
    elif user_message_lower in ["教學助理", "助理"]:
        reply_text = create_assistant_reply("教學助理")
    
    # 待辦事項
    elif user_message_lower in ["待辦", "待辦事項", "todo", "我的待辦"]:
        reply_message = create_todo_menu(user_id)
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[reply_message]
                )
            )
        return
    
    # 主選單
    elif user_message_lower in ["選單", "功能", "幫助", "help", "menu"]:
        reply_message = create_main_menu()
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[reply_message]
                )
            )
        return
    
    # 時間
    elif any(keyword in user_message_lower for keyword in ["時間", "現在幾點"]):
        now = datetime.now()
        reply_text = f"⏰ {now.strftime('%Y-%m-%d %H:%M:%S')}"
    
    # 計算
    elif user_message_lower.startswith("計算 "):
        try:
            expr = user_message_lower.replace("計算 ", "")
            result = eval(expr)
            reply_text = f"{expr} = {result}"
        except:
            reply_text = "計算格式錯誤，請用：計算 1+2"
    
    # 打招呼
    elif any(keyword in user_message_lower for keyword in ["你好", "嗨", "hi", "hello"]):
        reply_text = "嗨！點擊下方按鈕開始使用 🤖\n\n或輸入「選單」叫出功能表"
    
    # 預設（當作問教學助理）
    else:
        reply_text = create_assistant_reply(user_message)
    
    # 回覆文字訊息
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
