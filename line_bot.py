from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, TextMessage,
    QuickReply, QuickReplyItem, MessageAction
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, PostbackEvent, FollowEvent, LocationMessageContent
import os
from datetime import datetime
import random
import requests
import sqlite3
import json

CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")

app = Flask(__name__)

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# ========== 初始化資料庫 ==========
def init_db():
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    
    # 英文單字表
    c.execute('''CREATE TABLE IF NOT EXISTS vocabulary (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        word TEXT UNIQUE,
        meaning TEXT,
        example TEXT
    )''')
    
    # 教學提醒/問答表
    c.execute('''CREATE TABLE IF NOT EXISTS teaching (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        keyword TEXT UNIQUE,
        answer TEXT
    )''')
    
    # 待辦事項表
    c.execute('''CREATE TABLE IF NOT EXISTS todos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        task TEXT,
        created_at TEXT,
        status TEXT DEFAULT 'pending'
    )''')
    
    # 預設英文單字（如果沒有資料的話）
    c.execute("SELECT COUNT(*) FROM vocabulary")
    if c.fetchone()[0] == 0:
        default_vocab = [
            ("apple", "蘋果 🍎", "I eat an apple every day."),
            ("book", "書 📚", "This is a good book."),
            ("cat", "貓 🐱", "The cat is sleeping."),
            ("dog", "狗 🐶", "I have a dog."),
            ("sun", "太陽 ☀️", "The sun is shining."),
            ("moon", "月亮 🌙", "The moon is bright."),
            ("hello", "你好 👋", "Hello, nice to meet you!"),
            ("world", "世界 🌍", "Hello World!"),
            ("python", "蟒蛇/程式語言 🐍", "Python is a programming language."),
            ("teacher", "老師 👩‍🏫", "My teacher is kind."),
            ("student", "學生 🧑‍🎓", "I am a student."),
            ("homework", "作業 📝", "I need to do my homework."),
            ("exam", "考試 📋", "I have an exam tomorrow."),
        ]
        c.executemany("INSERT INTO vocabulary (word, meaning, example) VALUES (?, ?, ?)", default_vocab)
    
    # 預設教學問答
    c.execute("SELECT COUNT(*) FROM teaching")
    if c.fetchone()[0] == 0:
        default_teaching = [
            ("期末考", "📅 期末考時間：6/15-6/19，請提前準備！"),
            ("作業", "📝 作業請於每週五前上傳至數位學習平台。"),
            ("點名", "✅ 課程採隨機點名，缺席請依規定請假。"),
            ("成績", "📊 成績計算：期中考30%、期末考30%、作業40%。"),
            ("office hour", "👨‍🏫 教師輔導時間：每週三 14:00-16:00，請先預約。"),
            ("請假", "📋 請假請提前告知，並補交請假單。"),
        ]
        c.executemany("INSERT INTO teaching (keyword, answer) VALUES (?, ?)", default_teaching)
    
    conn.commit()
    conn.close()

init_db()

# ========== 資料庫操作函數 ==========
def get_vocab(word):
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("SELECT meaning, example FROM vocabulary WHERE word = ?", (word.lower(),))
    result = c.fetchone()
    conn.close()
    return result

def get_random_vocab():
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("SELECT word, meaning FROM vocabulary ORDER BY RANDOM() LIMIT 1")
    result = c.fetchone()
    conn.close()
    return result

def add_vocab(word, meaning, example=""):
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    try:
        c.execute("INSERT INTO vocabulary (word, meaning, example) VALUES (?, ?, ?)", (word.lower(), meaning, example))
        conn.commit()
        success = True
    except sqlite3.IntegrityError:
        success = False
    conn.close()
    return success

def get_teaching(keyword):
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("SELECT answer FROM teaching WHERE keyword = ?", (keyword,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

def add_teaching(keyword, answer):
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    try:
        c.execute("INSERT INTO teaching (keyword, answer) VALUES (?, ?)", (keyword, answer))
        conn.commit()
        success = True
    except sqlite3.IntegrityError:
        success = False
    conn.close()
    return success

def get_todos(user_id):
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("SELECT id, task FROM todos WHERE user_id = ? AND status = 'pending' ORDER BY id", (user_id,))
    result = c.fetchall()
    conn.close()
    return result

def add_todo(user_id, task):
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("INSERT INTO todos (user_id, task, created_at) VALUES (?, ?, ?)",
              (user_id, task, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit()
    conn.close()

def complete_todo(user_id, todo_id):
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("UPDATE todos SET status = 'done' WHERE id = ? AND user_id = ?", (todo_id, user_id))
    affected = c.rowcount
    conn.commit()
    conn.close()
    return affected > 0

def delete_todo(user_id, todo_id):
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("DELETE FROM todos WHERE id = ? AND user_id = ? AND status = 'pending'", (todo_id, user_id))
    affected = c.rowcount
    conn.commit()
    conn.close()
    return affected > 0

# ========== 天氣功能（用手機定位）==========
def get_weather_by_coords(lat, lon):
    """用經緯度查天氣（攝氏）"""
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true&temperature_unit=celsius&timezone=Asia/Taipei"
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            data = r.json()
            temp = data['current_weather']['temperature']
            weather_code = data['current_weather']['weathercode']
            weather_map = {
                0: "☀️ 晴", 1: "🌤️ 大致晴朗", 2: "⛅ 局部多雲", 3: "☁️ 陰",
                45: "🌫️ 霧", 48: "🌫️ 濃霧", 51: "🌦️ 毛毛雨", 61: "🌧️ 雨",
                71: "❄️ 雪", 95: "⛈️ 雷雨"
            }
            weather = weather_map.get(weather_code, "未知")
            return f"{weather}，{temp}°C"
    except Exception as e:
        print(f"天氣API錯誤: {e}")
    return "天氣資料暫時無法取得，請稍後再試"

def get_city_from_coords(lat, lon):
    """用經緯度取得城市名"""
    try:
        url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&accept-language=zh-TW"
        resp = requests.get(url, headers={'User-Agent': 'LineBot/1.0'}, timeout=5)
        data = resp.json()
        city = data.get('address', {}).get('city', '')
        if not city:
            city = data.get('address', {}).get('town', '')
        if not city:
            city = data.get('address', {}).get('county', '')
        return city if city else "您的位置"
    except:
        return "您的位置"

# ========== 常駐按鈕選單（兩字版）==========
def create_main_menu():
    """建立快速回覆按鈕選單（兩字版）"""
    return TextMessage(
        text="🤖 課程小幫手\n\n請選擇功能：",
        quick_reply=QuickReply(
            items=[
                QuickReplyItem(action=MessageAction(label="🌤️天氣", text="天氣")),
                QuickReplyItem(action=MessageAction(label="📚英字", text="單字")),
                QuickReplyItem(action=MessageAction(label="🎓教學", text="教學助理")),
                QuickReplyItem(action=MessageAction(label="✅待辦", text="待辦")),
            ]
        )
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

# ========== 加入好友時自動顯示選單 ==========
@handler.add(FollowEvent)
def handle_follow(event):
    """當使用者加入好友或解除封鎖時"""
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[create_main_menu()]
            )
        )

# ========== 位置訊息處理（天氣）==========
@handler.add(MessageEvent, message=LocationMessageContent)
def handle_location(event):
    """當使用者傳送位置時 - 回傳當地天氣"""
    lat = event.message.latitude
    lon = event.message.longitude
    
    city = get_city_from_coords(lat, lon)
    weather = get_weather_by_coords(lat, lon)
    
    reply = TextMessage(text=f"📍 {city}\n🌡️ {weather}")
    
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(reply_token=event.reply_token, messages=[reply])
        )

# ========== 按鈕點擊處理 ==========
@handler.add(PostbackEvent)
def handle_postback(event):
    data = event.postback.data
    user_id = event.source.user_id
    
    if data == "weather":
        reply = TextMessage(text="📍 請點選「＋」→「傳送位置」，我會告訴你當地天氣！")
    elif data == "vocab":
        result = get_random_vocab()
        if result:
            word, meaning = result
            reply = TextMessage(text=f"📖 {word} = {meaning}\n\n💡 輸入「查 單字」可查詢，輸入「新增單字 單字 意思」可新增")
        else:
            reply = TextMessage(text="📖 暫時沒有單字資料")
    elif data == "assistant":
        reply = TextMessage(text="🎓 教學助理上線！\n\n📌 可用指令：\n• 期末考 / 作業 / 成績\n• 查 apple\n• 新增單字 hello 你好\n• 新增提醒 考試時間 6/15")
    elif data == "todo":
        todos = get_todos(user_id)
        if todos:
            text = "✅ 待辦清單：\n" + "\n".join([f"{tid}. {task}" for tid, task in todos[:10]])
            text += "\n\n💡 完成請輸入「完成 編號」，刪除請輸入「刪除 編號」"
        else:
            text = "📋 目前沒有待辦事項\n\n💡 輸入「新增 買牛奶」來新增"
        reply = TextMessage(text=text)
    else:
        reply = create_main_menu()
    
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(reply_token=event.reply_token, messages=[reply])
        )

# ========== 文字訊息處理 ==========
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    msg = event.message.text.strip()
    msg_lower = msg.lower()
    user_id = event.source.user_id
    
    # 主選單
    if msg_lower in ["選單", "功能", "幫助", "menu"]:
        reply = create_main_menu()
    
    # 天氣（引導使用者傳送位置）
    elif msg_lower in ["天氣", "weather"]:
        reply = TextMessage(text="📍 請點選聊天室左下角的「＋」\n→ 選擇「傳送位置」\n→ 傳送後我就會告訴你當地天氣！")
    
    # ========== 英文單字功能 ==========
    elif msg_lower.startswith("查 "):
        word = msg_lower[3:]
        result = get_vocab(word)
        if result:
            meaning, example = result
            reply = TextMessage(text=f"📖 {word}\n意思：{meaning}\n例句：{example}")
        else:
            reply = TextMessage(text=f"❌ 查無「{word}」\n\n💡 可輸入「新增單字 {word} 意思」來新增")
    
    elif msg_lower == "單字":
        result = get_random_vocab()
        if result:
            word, meaning = result
            reply = TextMessage(text=f"📖 今日單字：{word} = {meaning}")
        else:
            reply = TextMessage(text="📖 暫時沒有單字資料")
    
    elif msg_lower.startswith("新增單字 "):
        parts = msg[5:].split(" ", 1)  # 跳過「新增單字 」5個字
        if len(parts) == 2:
            word, meaning = parts
            if add_vocab(word, meaning):
                reply = TextMessage(text=f"✅ 已新增單字：{word} = {meaning}")
            else:
                reply = TextMessage(text=f"⚠️ 單字「{word}」已存在！")
        else:
            reply = TextMessage(text="格式錯誤！請輸入：新增單字 apple 蘋果")
    
    # ========== 教學助理功能 ==========
    elif msg_lower == "教學助理":
        reply = TextMessage(text="🎓 教學助理上線！\n\n📌 試試看：\n• 期末考 / 作業 / 成績\n• 查 apple\n• 新增單字 hello 你好\n• 新增提醒 考試時間 6/15")
    
    elif msg_lower.startswith("新增提醒 "):
        parts = msg[5:].split(" ", 1)  # 跳過「新增提醒 」5個字
        if len(parts) == 2:
            keyword, answer = parts
            if add_teaching(keyword, answer):
                reply = TextMessage(text=f"✅ 已新增提醒：{keyword} → {answer}")
            else:
                reply = TextMessage(text=f"⚠️ 關鍵字「{keyword}」已存在！可用「修改提醒」功能")
        else:
            reply = TextMessage(text="格式錯誤！請輸入：新增提醒 期末考 6/15考試")
    
    else:
        # 查詢教學資料庫
        teaching_answer = get_teaching(msg_lower)
        if teaching_answer:
            reply = TextMessage(text=teaching_answer)
        
        # 計算功能
        elif msg_lower.startswith("計算 "):
            try:
                expr = msg_lower[3:]
                result = eval(expr)
                reply = TextMessage(text=f"{expr} = {result}")
            except:
                reply = TextMessage(text="計算錯誤，請用：計算 1+2")
        
        # 時間功能
        elif "時間" in msg_lower or "幾點" in msg_lower:
            now = datetime.now()
            reply = TextMessage(text=f"⏰ {now.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # ========== 待辦事項功能 ==========
        elif msg_lower.startswith("新增 "):
            task = msg[3:]
            add_todo(user_id, task)
            todos_list = get_todos(user_id)
            reply = TextMessage(text=f"✅ 已新增：{task}\n📋 目前共 {len(todos_list)} 項待辦")
        
        elif msg_lower in ["待辦", "待辦事項", "todo"]:
            todos_list = get_todos(user_id)
            if todos_list:
                text = "✅ 待辦清單：\n" + "\n".join([f"{tid}. {task}" for tid, task in todos_list[:10]])
                text += "\n\n💡 完成請輸入「完成 編號」，刪除請輸入「刪除 編號」"
            else:
                text = "📋 沒有待辦事項\n\n💡 輸入「新增 買牛奶」來新增"
            reply = TextMessage(text=text)
        
        elif msg_lower.startswith("完成 "):
            try:
                todo_id = int(msg_lower[3:])
                if complete_todo(user_id, todo_id):
                    reply = TextMessage(text=f"✅ 已完成編號 {todo_id} 的待辦事項！")
                else:
                    reply = TextMessage(text="❌ 找不到該編號，請輸入「待辦」查看編號")
            except:
                reply = TextMessage(text="請輸入：完成 1")
        
        elif msg_lower.startswith("刪除 "):
            try:
                todo_id = int(msg_lower[3:])
                if delete_todo(user_id, todo_id):
                    reply = TextMessage(text=f"🗑️ 已刪除編號 {todo_id} 的待辦事項！")
                else:
                    reply = TextMessage(text="❌ 找不到該編號，請輸入「待辦」查看編號")
            except:
                reply = TextMessage(text="請輸入：刪除 1")
        
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
