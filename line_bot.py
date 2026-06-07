from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, PushMessageRequest, TextMessage,
    QuickReply, QuickReplyItem, MessageAction
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, PostbackEvent, FollowEvent, LocationMessageContent
import os
from datetime import datetime
import random
import requests
import sqlite3
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")  # 管理後台密碼

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
    
    # 三個科目的教學內容
    c.execute('''CREATE TABLE IF NOT EXISTS subjects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE,
        description TEXT,
        schedule TEXT,
        deadline TEXT
    )''')
    
    # 待辦事項表
    c.execute('''CREATE TABLE IF NOT EXISTS todos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        task TEXT,
        todo_date TEXT,
        created_at TEXT,
        status TEXT DEFAULT 'pending'
    )''')
    
    # 使用者推播設定
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY,
        nickname TEXT,
        push_enabled INTEGER DEFAULT 1,
        created_at TEXT
    )''')
    
    # 預設英文單字
    c.execute("SELECT COUNT(*) FROM vocabulary")
    if c.fetchone()[0] == 0:
        default_vocab = [
            ("apple", "蘋果 🍎", "I eat an apple every day."),
            ("book", "書 📚", "This is a good book."),
            ("cat", "貓 🐱", "The cat is sleeping."),
            ("dog", "狗 🐶", "I have a dog."),
            ("statistics", "統計學 📊", "Statistics is important for research."),
            ("sociology", "社會學 👥", "Sociology studies human society."),
            ("outdoor", "戶外探索 🏕️", "Outdoor education is fun."),
        ]
        c.executemany("INSERT INTO vocabulary (word, meaning, example) VALUES (?, ?, ?)", default_vocab)
    
    # 預設三個科目
    c.execute("SELECT COUNT(*) FROM subjects")
    if c.fetchone()[0] == 0:
        default_subjects = [
            ("實驗設計與統計", "📊 本課程介紹實驗設計原理與統計分析方法", "每週二 9:00-12:00", "期末報告：6/15"),
            ("運動社會學", "⚽ 探討運動與社會的互動關係", "每週三 14:00-17:00", "期末論文：6/20"),
            ("探索教育", "🏕️ 體驗式學習與戶外冒險教育", "每週四 9:00-12:00", "戶外實作：6/10"),
        ]
        c.executemany("INSERT INTO subjects (name, description, schedule, deadline) VALUES (?, ?, ?, ?)", default_subjects)
    
    conn.commit()
    conn.close()

init_db()

# ========== 資料庫操作函數 ==========
def get_subjects():
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("SELECT name, description, schedule, deadline FROM subjects")
    result = c.fetchall()
    conn.close()
    return result

def get_subject(name):
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("SELECT description, schedule, deadline FROM subjects WHERE name = ?", (name,))
    result = c.fetchone()
    conn.close()
    return result

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

def get_todos_by_date(user_id, date_str):
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("SELECT id, task FROM todos WHERE user_id = ? AND todo_date = ? AND status = 'pending'", (user_id, date_str))
    result = c.fetchall()
    conn.close()
    return result

def get_all_todos(user_id):
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("SELECT id, task, todo_date FROM todos WHERE user_id = ? AND status = 'pending' ORDER BY todo_date", (user_id,))
    result = c.fetchall()
    conn.close()
    return result

def add_todo(user_id, task, todo_date=None):
    if todo_date is None:
        todo_date = datetime.now().strftime('%Y-%m-%d')
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("INSERT INTO todos (user_id, task, todo_date, created_at) VALUES (?, ?, ?, ?)",
              (user_id, task, todo_date, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
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

def register_user(user_id, nickname=None):
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, nickname, created_at) VALUES (?, ?, ?)",
              (user_id, nickname, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE push_enabled = 1")
    result = [row[0] for row in c.fetchall()]
    conn.close()
    return result

# ========== 天氣功能 ==========
def get_weather_by_coords(lat, lon):
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true&temperature_unit=celsius&timezone=Asia/Taipei"
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            data = r.json()
            temp = data['current_weather']['temperature']
            weather_code = data['current_weather']['weathercode']
            weather_map = {0: "☀️ 晴", 1: "🌤️ 大致晴朗", 2: "⛅ 局部多雲", 3: "☁️ 陰", 45: "🌫️ 霧", 61: "🌧️ 雨", 95: "⛈️ 雷雨"}
            weather = weather_map.get(weather_code, "未知")
            return f"{weather}，{temp}°C"
    except:
        pass
    return "天氣資料暫時無法取得"

def get_city_from_coords(lat, lon):
    try:
        url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&accept-language=zh-TW"
        resp = requests.get(url, headers={'User-Agent': 'LineBot/1.0'}, timeout=5)
        data = resp.json()
        city = data.get('address', {}).get('city', '') or data.get('address', {}).get('town', '') or data.get('address', {}).get('county', '')
        return city if city else "您的位置"
    except:
        return "您的位置"

# ========== 常駐按鈕選單 ==========
def create_main_menu():
    return TextMessage(
        text="🤖 課程小幫手\n\n請選擇功能：",
        quick_reply=QuickReply(
            items=[
                QuickReplyItem(action=MessageAction(label="🌤️天氣", text="天氣")),
                QuickReplyItem(action=MessageAction(label="📚英字", text="單字")),
                QuickReplyItem(action=MessageAction(label="📊統計", text="實驗設計與統計")),
                QuickReplyItem(action=MessageAction(label="⚽社會", text="運動社會學")),
                QuickReplyItem(action=MessageAction(label="🏕️探索", text="探索教育")),
                QuickReplyItem(action=MessageAction(label="✅待辦", text="待辦")),
            ]
        )
    )

# ========== 推送待辦事項 ==========
def push_todos():
    """每天早上7點推送當日待辦，晚上9點推送隔日待辦"""
    tz = pytz.timezone('Asia/Taipei')
    now = datetime.now(tz)
    current_date = now.strftime('%Y-%m-%d')
    
    # 判斷是早上7點還是晚上9點
    if now.hour == 7:
        title = "🌅 早安！今天的待辦事項："
        date_str = current_date
    elif now.hour == 21:
        title = "🌙 晚安！明天的待辦事項："
        # 明天日期
        from datetime import timedelta
        tomorrow = now + timedelta(days=1)
        date_str = tomorrow.strftime('%Y-%m-%d')
    else:
        return
    
    users = get_all_users()
    for user_id in users:
        todos = get_todos_by_date(user_id, date_str)
        if todos:
            todo_list = "\n".join([f"{i+1}. {task}" for i, (_, task) in enumerate(todos)])
            message = f"{title}\n\n{todo_list}\n\n💡 完成後請輸入「完成 編號」"
        else:
            message = f"{title}\n\n📋 目前沒有待辦事項\n\n💡 輸入「新增 任務 日期」來新增，例如：新增 交作業 2026-06-08"
        
        try:
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
                line_bot_api.push_message(
                    PushMessageRequest(to=user_id, messages=[TextMessage(text=message)])
                )
        except Exception as e:
            print(f"推播失敗 {user_id}: {e}")

# ========== 啟動排程 ==========
scheduler = BackgroundScheduler(timezone='Asia/Taipei')
scheduler.add_job(push_todos, CronTrigger(hour=7, minute=0))   # 早上7點
scheduler.add_job(push_todos, CronTrigger(hour=21, minute=0))  # 晚上9點
scheduler.start()

# ========== LINE Bot 路由 ==========
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

@handler.add(FollowEvent)
def handle_follow(event):
    user_id = event.source.user_id
    register_user(user_id)
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[create_main_menu()]
            )
        )

@handler.add(MessageEvent, message=LocationMessageContent)
def handle_location(event):
    lat = event.message.latitude
    lon = event.message.longitude
    city = get_city_from_coords(lat, lon)
    weather = get_weather_by_coords(lat, lon)
    
    reply = TextMessage(text=f"📍 {city}\n🌡️ {weather}\n\n💡 試試其他功能：\n• 實驗設計與統計\n• 運動社會學\n• 探索教育")
    
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(reply_token=event.reply_token, messages=[reply])
        )

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    msg = event.message.text.strip()
    msg_lower = msg.lower()
    user_id = event.source.user_id
    
    # 註冊使用者
    register_user(user_id)
    
    # 主選單
    if msg_lower in ["選單", "功能", "幫助", "menu"]:
        reply = create_main_menu()
    
    # 天氣引導
    elif msg_lower in ["天氣", "weather"]:
        reply = TextMessage(
            text="📍 如何傳送位置？\n\n1️⃣ 點選聊天室左下角的「＋」\n2️⃣ 選擇「位置」\n3️⃣ 點選「傳送目前位置」\n\n收到位置後我就會告訴你當地天氣！",
            quick_reply=QuickReply(
                items=[QuickReplyItem(action=MessageAction(label="🌤️我知道了", text="幫助"))]
            )
        )
    
    # 三個科目查詢
    elif msg_lower in ["實驗設計與統計", "統計", "實驗設計"]:
        subject = get_subject("實驗設計與統計")
        if subject:
            desc, schedule, deadline = subject
            reply = TextMessage(text=f"📊 實驗設計與統計\n\n📖 {desc}\n\n🕐 上課時間：{schedule}\n\n📅 {deadline}")
        else:
            reply = TextMessage(text="📊 實驗設計與統計課程資訊即將上線！")
    
    elif msg_lower in ["運動社會學", "社會學", "運動"]:
        subject = get_subject("運動社會學")
        if subject:
            desc, schedule, deadline = subject
            reply = TextMessage(text=f"⚽ 運動社會學\n\n📖 {desc}\n\n🕐 上課時間：{schedule}\n\n📅 {deadline}")
        else:
            reply = TextMessage(text="⚽ 運動社會學課程資訊即將上線！")
    
    elif msg_lower in ["探索教育", "探索", "戶外"]:
        subject = get_subject("探索教育")
        if subject:
            desc, schedule, deadline = subject
            reply = TextMessage(text=f"🏕️ 探索教育\n\n📖 {desc}\n\n🕐 上課時間：{schedule}\n\n📅 {deadline}")
        else:
            reply = TextMessage(text="🏕️ 探索教育課程資訊即將上線！")
    
    # 英文單字
    elif msg_lower.startswith("查 "):
        word = msg_lower[3:]
        result = get_vocab(word)
        if result:
            meaning, example = result
            reply = TextMessage(text=f"📖 {word}\n意思：{meaning}\n例句：{example}")
        else:
            reply = TextMessage(text=f"❌ 查無「{word}」\n\n💡 可輸入「新增單字 單字 意思」來新增")
    
    elif msg_lower == "單字":
        result = get_random_vocab()
        if result:
            word, meaning = result
            reply = TextMessage(text=f"📖 今日單字：{word} = {meaning}")
        else:
            reply = TextMessage(text="📖 暫時沒有單字資料")
    
    elif msg_lower.startswith("新增單字 "):
        parts = msg[5:].split(" ", 1)
        if len(parts) == 2:
            word, meaning = parts
            if add_vocab(word, meaning):
                reply = TextMessage(text=f"✅ 已新增單字：{word} = {meaning}")
            else:
                reply = TextMessage(text=f"⚠️ 單字「{word}」已存在！")
        else:
            reply = TextMessage(text="格式錯誤！請輸入：新增單字 apple 蘋果")
    
    # 待辦事項（支援日期）
    elif msg_lower.startswith("新增 "):
        task_part = msg[3:]
        todo_date = None
        task = task_part
        
        # 檢查是否有日期（格式：YYYY-MM-DD）
        import re
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', task_part)
        if date_match:
            todo_date = date_match.group(1)
            task = task_part.replace(todo_date, '').strip()
        
        if not task:
            task = "待辦事項"
        
        add_todo(user_id, task, todo_date)
        date_str = todo_date if todo_date else "今天"
        reply = TextMessage(text=f"✅ 已新增：{task}\n📅 日期：{date_str}\n\n💡 輸入「待辦」查看所有事項")
    
    elif msg_lower in ["待辦", "待辦事項", "todo"]:
        todos = get_all_todos(user_id)
        if todos:
            text = "✅ 待辦清單：\n"
            for tid, task, date_str in todos:
                text += f"{tid}. [{date_str}] {task}\n"
            text += "\n💡 完成請輸入「完成 編號」\n💡 刪除請輸入「刪除 編號」"
        else:
            text = "📋 沒有待辦事項\n\n💡 新增範例：\n• 新增 交作業\n• 新增 期末報告 2026-06-15"
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
    
    # 計算
    elif msg_lower.startswith("計算 "):
        try:
            expr = msg_lower[3:]
            result = eval(expr)
            reply = TextMessage(text=f"{expr} = {result}")
        except:
            reply = TextMessage(text="計算錯誤，請用：計算 1+2")
    
    # 時間
    elif "時間" in msg_lower or "幾點" in msg_lower:
        now = datetime.now()
        reply = TextMessage(text=f"⏰ {now.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 預設（附帶按鈕）
    else:
        reply = TextMessage(
            text=f"你說了：「{msg}」\n\n📌 試試看：\n• 實驗設計與統計\n• 運動社會學\n• 探索教育\n• 新增 買牛奶\n• 單字",
            quick_reply=QuickReply(
                items=[
                    QuickReplyItem(action=MessageAction(label="📊統計", text="實驗設計與統計")),
                    QuickReplyItem(action=MessageAction(label="⚽社會", text="運動社會學")),
                    QuickReplyItem(action=MessageAction(label="🏕️探索", text="探索教育")),
                    QuickReplyItem(action=MessageAction(label="✅待辦", text="待辦")),
                ]
            )
        )
    
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(reply_token=event.reply_token, messages=[reply])
        )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True)
