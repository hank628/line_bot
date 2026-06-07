from flask import Flask, request, abort, render_template_string, redirect, session, jsonify
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, PushMessageRequest, TextMessage,
    QuickReply, QuickReplyItem, MessageAction
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, FollowEvent, LocationMessageContent
import os
import sqlite3
import requests
import random
import re
from datetime import datetime, timedelta
from functools import wraps
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

# ========== 設定 ==========
CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
SECRET_KEY = os.environ.get("SECRET_KEY", "your-secret-key-here")

app = Flask(__name__)
app.secret_key = SECRET_KEY

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# ========== 初始化資料庫（修正版）==========
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
    
    # 統計專有名詞表（欄位順序修正）
    c.execute('''CREATE TABLE IF NOT EXISTS statistics_glossary (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        term TEXT UNIQUE,
        translation TEXT,
        definition TEXT,
        code TEXT,
        is_starred INTEGER DEFAULT 0
    )''')
    
    # 運動社會學專有名詞表
    c.execute('''CREATE TABLE IF NOT EXISTS sociology_glossary (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        term TEXT UNIQUE,
        translation TEXT,
        definition TEXT,
        is_starred INTEGER DEFAULT 0
    )''')
    
    # 探索教育專有名詞表
    c.execute('''CREATE TABLE IF NOT EXISTS outdoor_glossary (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        term TEXT UNIQUE,
        translation TEXT,
        definition TEXT,
        is_starred INTEGER DEFAULT 0
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
    
    # 使用者表
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY,
        created_at TEXT
    )''')
    
    # 預設英文單字
    c.execute("SELECT COUNT(*) FROM vocabulary")
    if c.fetchone()[0] == 0:
        default_vocab = [
            ("apple", "蘋果 🍎", "I eat an apple every day."),
            ("book", "書 📚", "This is a good book."),
            ("statistics", "統計學 📊", "Statistics is important for research."),
            ("sociology", "社會學 👥", "Sociology studies human society."),
            ("outdoor", "戶外探索 🏕️", "Outdoor education is fun."),
        ]
        c.executemany("INSERT INTO vocabulary (word, meaning, example) VALUES (?, ?, ?)", default_vocab)
    
    # 預設統計名詞
    c.execute("SELECT COUNT(*) FROM statistics_glossary")
    if c.fetchone()[0] == 0:
        default_stats = [
            ("t-test", "t檢定", "比較兩組樣本平均數是否有顯著差異的統計方法", "from scipy import stats\nt_stat, p_value = stats.ttest_ind(group1, group2)", 1),
            ("ANOVA", "變異數分析", "比較三組以上樣本平均數是否有顯著差異", "from scipy import stats\nf_stat, p_value = stats.f_oneway(group1, group2, group3)", 1),
            ("correlation", "相關分析", "探討兩個連續變數之間的線性關係強度", "from scipy import stats\nr, p_value = stats.pearsonr(x, y)", 1),
            ("regression", "迴歸分析", "建立自變數與依變數之間的預測模型", "from sklearn.linear_model import LinearRegression\nmodel = LinearRegression()\nmodel.fit(X, y)", 1),
            ("Chi-square", "卡方檢定", "檢驗兩個類別變數之間是否獨立", "from scipy import stats\nchi2, p_value, dof, expected = stats.chi2_contingency(contingency_table)", 0),
            ("p-value", "p值", "在虛無假設為真下，觀察到當前結果或更極端結果的機率", "if p_value < 0.05:\n    print('統計顯著')", 1),
        ]
        c.executemany("INSERT INTO statistics_glossary (term, translation, definition, code, is_starred) VALUES (?, ?, ?, ?, ?)", default_stats)
    
    # 預設社會學名詞
    c.execute("SELECT COUNT(*) FROM sociology_glossary")
    if c.fetchone()[0] == 0:
        default_socio = [
            ("sports socialization", "運動社會化", "個人透過運動參與學習社會規範、價值觀和行為模式的過程", 1),
            ("social stratification", "社會階層化", "社會依據財富、權力、聲望等資源將人群分層的現象", 1),
            ("gender ideology", "性別意識形態", "社會對男性與女性在運動中應有的角色、行為和價值的期待", 1),
            ("sports fan", "運動迷", "對特定運動隊伍、運動員或運動項目有強烈情感認同和支持的人", 1),
            ("conflict theory", "衝突理論", "檢視運動如何反映和強化社會不平等與權力關係", 1),
            ("doping", "禁藥使用", "運動員使用禁用物質以提升表現，涉及倫理與健康議題", 1),
        ]
        c.executemany("INSERT INTO sociology_glossary (term, translation, definition, is_starred) VALUES (?, ?, ?, ?)", default_socio)
    
    # 預設探索教育名詞
    c.execute("SELECT COUNT(*) FROM outdoor_glossary")
    if c.fetchone()[0] == 0:
        default_outdoor = [
            ("experiential learning", "體驗式學習", "透過直接經驗和反思來學習的循環過程", 1),
            ("challenge by choice", "自願挑戰", "參與者可依自身意願決定是否參與及參與程度", 1),
            ("full value contract", "全價值契約", "團體成員共同建立的參與規範、目標和承諾", 1),
            ("debriefing", "反思回饋", "活動結束後引導參與者分享經驗、感受和學習的結構化討論過程", 1),
            ("stretch zone", "伸展圈", "在支持環境下適度挑戰自我，促進成長的區域", 1),
        ]
        c.executemany("INSERT INTO outdoor_glossary (term, translation, definition, is_starred) VALUES (?, ?, ?, ?)", default_outdoor)
    
    conn.commit()
    conn.close()

init_db()

# ========== 常駐按鈕選單（每次回覆都附帶）==========
def get_main_quick_reply():
    return QuickReply(
        items=[
            QuickReplyItem(action=MessageAction(label="🌤️天氣", text="天氣")),
            QuickReplyItem(action=MessageAction(label="📚英字", text="單字")),
            QuickReplyItem(action=MessageAction(label="📚課程", text="課程")),
            QuickReplyItem(action=MessageAction(label="✅待辦", text="待辦")),
        ]
    )

def get_course_quick_reply():
    return QuickReply(
        items=[
            QuickReplyItem(action=MessageAction(label="📊統計", text="統計")),
            QuickReplyItem(action=MessageAction(label="⚽社會", text="運動社會學")),
            QuickReplyItem(action=MessageAction(label="🏕️探索", text="探索教育")),
            QuickReplyItem(action=MessageAction(label="◀️回主選單", text="幫助")),
        ]
    )

# ========== 天氣函數（修正為中文）==========
def get_weather(lat, lon):
    try:
        url = f"https://wttr.in/{lat},{lon}?format=%C+%t&lang=zh"
        response = requests.get(url, timeout=8)
        if response.status_code == 200 and response.text.strip():
            weather_text = response.text.strip()
            # 將英文天氣轉中文
            weather_map = {
                'Sunny': '晴天', 'Clear': '晴朗', 'Partly cloudy': '多雲時晴',
                'Cloudy': '陰天', 'Overcast': '陰天', 'Rain': '雨天',
                'Light rain': '小雨', 'Moderate rain': '中雨', 'Heavy rain': '大雨',
                'Thunderstorm': '雷雨', 'Snow': '雪', 'Mist': '霧', 'Fog': '濃霧'
            }
            for en, zh in weather_map.items():
                if en in weather_text:
                    weather_text = weather_text.replace(en, zh)
            return weather_text
    except:
        pass
    
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true&temperature_unit=celsius&timezone=Asia/Taipei"
        response = requests.get(url, timeout=8)
        if response.status_code == 200:
            data = response.json()
            temp = data['current_weather']['temperature']
            code = data['current_weather']['weathercode']
            weather_codes = {0: "晴天", 1: "晴時多雲", 2: "多雲", 3: "陰天", 61: "下雨", 95: "雷雨"}
            weather = weather_codes.get(code, "未知")
            return f"{weather}，{temp}°C"
    except:
        pass
    
    conditions = ["晴天", "多雲時晴", "晴時多雲", "陰天"]
    temps = ["22-26°C", "23-27°C", "24-28°C", "21-25°C"]
    return f"{random.choice(conditions)}，{random.choice(temps)}"

def get_city(lat, lon):
    try:
        url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&accept-language=zh-TW"
        r = requests.get(url, headers={'User-Agent': 'LineBot/1.0'}, timeout=5)
        data = r.json()
        city = data.get('address', {}).get('city', '') or data.get('address', {}).get('town', '') or data.get('address', {}).get('county', '')
        return city if city else "您的位置"
    except:
        return "您的位置"

# ========== 課程查詢函數 ==========
PAGE_SIZE = 10

def get_glossary_paginated(table, page, show_starred_only=False):
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    offset = (page - 1) * PAGE_SIZE
    if show_starred_only:
        c.execute(f"SELECT id, term, translation, definition, code, is_starred FROM {table} WHERE is_starred = 1 ORDER BY term LIMIT ? OFFSET ?", (PAGE_SIZE, offset))
        total = c.execute(f"SELECT COUNT(*) FROM {table} WHERE is_starred = 1").fetchone()[0]
    else:
        c.execute(f"SELECT id, term, translation, definition, code, is_starred FROM {table} ORDER BY term LIMIT ? OFFSET ?", (PAGE_SIZE, offset))
        total = c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    data = c.fetchall()
    conn.close()
    return data, total

def search_glossary(table, keyword):
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute(f"SELECT id, term, translation, definition, code FROM {table} WHERE term LIKE ? OR translation LIKE ? LIMIT 5", (f'%{keyword}%', f'%{keyword}%'))
    results = c.fetchall()
    conn.close()
    return results

# ========== 待辦推播 ==========
def push_todos():
    tz = pytz.timezone('Asia/Taipei')
    now = datetime.now(tz)
    
    if now.hour == 7:
        title = "🌅 早安！今天的待辦事項："
        date_str = now.strftime('%Y-%m-%d')
    elif now.hour == 21:
        title = "🌙 晚安！明天的待辦事項："
        date_str = (now + timedelta(days=1)).strftime('%Y-%m-%d')
    else:
        return
    
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    users = [row[0] for row in c.fetchall()]
    conn.close()
    
    for user_id in users:
        conn = sqlite3.connect('course_bot.db')
        c = conn.cursor()
        c.execute("SELECT id, task FROM todos WHERE user_id = ? AND todo_date = ? AND status = 'pending'", (user_id, date_str))
        todos = c.fetchall()
        conn.close()
        
        if todos:
            todo_list = "\n".join([f"{i+1}. {task}" for i, (_, task) in enumerate(todos)])
            message = f"{title}\n\n{todo_list}\n\n💡 完成請輸入「完成 編號」"
        else:
            message = f"{title}\n\n📋 目前沒有待辦事項"
        
        try:
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
                line_bot_api.push_message(PushMessageRequest(to=user_id, messages=[TextMessage(text=message)]))
        except Exception as e:
            print(f"推播失敗 {user_id}: {e}")

# ========== 啟動排程 ==========
scheduler = BackgroundScheduler(timezone='Asia/Taipei')
scheduler.add_job(push_todos, CronTrigger(hour=7, minute=0))
scheduler.add_job(push_todos, CronTrigger(hour=21, minute=0))
scheduler.start()

# ========== LINE Bot 路由 ==========
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

@handler.add(FollowEvent)
def handle_follow(event):
    user_id = event.source.user_id
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, created_at) VALUES (?, ?)", 
              (user_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit()
    conn.close()
    
    # 初次加入直接顯示歡迎訊息 + 按鈕
    welcome_text = "🤖 歡迎使用 HANK EduMentor！\n\n📌 下方按鈕可直接點選：\n• 🌤️天氣 - 傳送位置查天氣\n• 📚英字 - 隨機英文單字\n• 📚課程 - 三種課程專有名詞\n• ✅待辦 - 管理待辦事項"
    
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=welcome_text, quick_reply=get_main_quick_reply())]
            )
        )

@handler.add(MessageEvent, message=LocationMessageContent)
def handle_location(event):
    lat = event.message.latitude
    lon = event.message.longitude
    city = get_city(lat, lon)
    weather = get_weather(lat, lon)
    
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=f"📍 {city}\n🌡️ {weather}", quick_reply=get_main_quick_reply())]
            )
        )

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    msg = event.message.text.strip()
    msg_lower = msg.lower()
    user_id = event.source.user_id
    
    # 註冊使用者
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, created_at) VALUES (?, ?)", 
              (user_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit()
    conn.close()
    
    # 主選單 - 輸入幫助或選單都顯示按鈕
    if msg_lower in ["幫助", "選單", "menu", "help"]:
        reply = TextMessage(
            text="🤖 HANK EduMentor\n\n📌 點擊下方按鈕使用功能：",
            quick_reply=get_main_quick_reply()
        )
    
    # 課程選單
    elif msg_lower in ["課程", "course"]:
        reply = TextMessage(
            text="📚 請選擇科目：",
            quick_reply=get_course_quick_reply()
        )
    
    # 天氣
    elif msg_lower in ["天氣", "weather"]:
        reply = TextMessage(
            text="📍 如何取得天氣？\n\n1️⃣ 點選左下角「＋」\n2️⃣ 選擇「位置」\n3️⃣ 傳送目前位置",
            quick_reply=get_main_quick_reply()
        )
    
    # 英文單字
    elif msg_lower in ["單字", "english", "vocab"]:
        conn = sqlite3.connect('course_bot.db')
        c = conn.cursor()
        c.execute("SELECT word, meaning FROM vocabulary ORDER BY RANDOM() LIMIT 1")
        result = c.fetchone()
        conn.close()
        if result:
            reply = TextMessage(text=f"📖 {result[0]} = {result[1]}", quick_reply=get_main_quick_reply())
        else:
            reply = TextMessage(text="📖 暫無單字", quick_reply=get_main_quick_reply())
    
    # ========== 統計 ==========
    elif msg_lower in ["統計", "實驗設計與統計", "statistics"]:
        session['stats_page'] = 1
        session['stats_mode'] = 'all'
        data, total = get_glossary_paginated('statistics_glossary', 1, False)
        total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
        
        if data:
            text = f"📊 實驗設計與統計 (第1頁/共{total_pages}頁)\n\n"
            for i, (idx, term, trans, definition, code, starred) in enumerate(data, 1):
                star = "⭐ " if starred else ""
                text += f"{i}. {star}{term} - {trans}\n"
            text += f"\n💡 指令：\n• 輸入數字 (1~{len(data)}) 查詳細\n• 輸入「下一頁」/「上一頁」\n• 輸入「核心」看精選\n• 輸入「查 [關鍵字]」搜尋"
            reply = TextMessage(text=text, quick_reply=get_course_quick_reply())
        else:
            reply = TextMessage(text="📊 暫無統計資料", quick_reply=get_course_quick_reply())
    
    elif msg_lower == "核心" and session.get('stats_mode') is not None:
        session['stats_mode'] = 'starred'
        session['stats_page'] = 1
        data, total = get_glossary_paginated('statistics_glossary', 1, True)
        total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
        
        if data:
            text = f"📊 統計核心名詞 (第1頁/共{total_pages}頁)\n\n"
            for i, (idx, term, trans, definition, code, starred) in enumerate(data, 1):
                text += f"{i}. {term} - {trans}\n"
            text += f"\n💡 輸入數字查詳細"
            reply = TextMessage(text=text, quick_reply=get_course_quick_reply())
        else:
            reply = TextMessage(text="📊 暫無核心名詞", quick_reply=get_course_quick_reply())
    
    # ========== 運動社會學 ==========
    elif msg_lower in ["運動社會學", "社會學", "sociology"]:
        session['socio_page'] = 1
        session['socio_mode'] = 'starred'
        data, total = get_glossary_paginated('sociology_glossary', 1, True)
        total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
        
        if data:
            text = f"⚽ 運動社會學核心名詞 (第1頁/共{total_pages}頁)\n\n"
            for i, (idx, term, trans, definition, code, starred) in enumerate(data, 1):
                text += f"{i}. {term} - {trans}\n"
            text += f"\n💡 指令：\n• 輸入數字查詳細\n• 輸入「全部」看所有名詞\n• 輸入「查 [關鍵字]」搜尋"
            reply = TextMessage(text=text, quick_reply=get_course_quick_reply())
        else:
            reply = TextMessage(text="⚽ 暫無社會學資料", quick_reply=get_course_quick_reply())
    
    elif msg_lower == "全部" and session.get('socio_mode') is not None:
        session['socio_mode'] = 'all'
        session['socio_page'] = 1
        data, total = get_glossary_paginated('sociology_glossary', 1, False)
        total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
        
        text = f"⚽ 運動社會學全部名詞 (第1頁/共{total_pages}頁)\n\n"
        for i, (idx, term, trans, definition, code, starred) in enumerate(data, 1):
            star = "⭐ " if starred else ""
            text += f"{i}. {star}{term} - {trans}\n"
        text += f"\n💡 輸入數字查詳細，或輸入「核心」看精選"
        reply = TextMessage(text=text, quick_reply=get_course_quick_reply())
    
    # ========== 探索教育 ==========
    elif msg_lower in ["探索教育", "探索", "outdoor"]:
        session['outdoor_page'] = 1
        session['outdoor_mode'] = 'all'
        data, total = get_glossary_paginated('outdoor_glossary', 1, False)
        total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
        
        if data:
            text = f"🏕️ 探索教育 (第1頁/共{total_pages}頁)\n\n"
            for i, (idx, term, trans, definition, code, starred) in enumerate(data, 1):
                star = "⭐ " if starred else ""
                text += f"{i}. {star}{term} - {trans}\n"
            text += f"\n💡 指令：\n• 輸入數字查詳細\n• 輸入「下一頁」/「上一頁」\n• 輸入「核心」看精選\n• 輸入「查 [關鍵字]」搜尋"
            reply = TextMessage(text=text, quick_reply=get_course_quick_reply())
        else:
            reply = TextMessage(text="🏕️ 暫無探索教育資料", quick_reply=get_course_quick_reply())
    
    # ========== 分頁處理 ==========
    elif msg_lower in ["下一頁", "上一頁"]:
        if session.get('stats_page') is not None:
            page = session.get('stats_page', 1)
            mode = session.get('stats_mode', 'all')
            if msg_lower == "下一頁":
                page += 1
            else:
                page -= 1
            page = max(1, page)
            data, total = get_glossary_paginated('statistics_glossary', page, mode == 'starred')
            total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
            if page > total_pages:
                page = total_pages
                data, total = get_glossary_paginated('statistics_glossary', page, mode == 'starred')
            session['stats_page'] = page
            
            if data:
                text = f"📊 實驗設計與統計 (第{page}頁/共{total_pages}頁)\n\n"
                for i, (idx, term, trans, definition, code, starred) in enumerate(data, 1):
                    star = "⭐ " if starred else ""
                    text += f"{i}. {star}{term} - {trans}\n"
                text += f"\n💡 輸入數字查詳細"
                reply = TextMessage(text=text, quick_reply=get_course_quick_reply())
            else:
                reply = TextMessage(text="📊 暫無資料", quick_reply=get_course_quick_reply())
        
        elif session.get('outdoor_page') is not None:
            page = session.get('outdoor_page', 1)
            mode = session.get('outdoor_mode', 'all')
            if msg_lower == "下一頁":
                page += 1
            else:
                page -= 1
            page = max(1, page)
            data, total = get_glossary_paginated('outdoor_glossary', page, mode == 'starred')
            total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
            if page > total_pages:
                page = total_pages
                data, total = get_glossary_paginated('outdoor_glossary', page, mode == 'starred')
            session['outdoor_page'] = page
            
            text = f"🏕️ 探索教育 (第{page}頁/共{total_pages}頁)\n\n"
            for i, (idx, term, trans, definition, code, starred) in enumerate(data, 1):
                star = "⭐ " if starred else ""
                text += f"{i}. {star}{term} - {trans}\n"
            text += f"\n💡 輸入數字查詳細"
            reply = TextMessage(text=text, quick_reply=get_course_quick_reply())
        else:
            reply = TextMessage(text="請先選擇一個科目", quick_reply=get_main_quick_reply())
    
    # ========== 數字查詢 ==========
    elif msg_lower.isdigit():
        num = int(msg_lower)
        if session.get('stats_page') is not None:
            page = session.get('stats_page', 1)
            mode = session.get('stats_mode', 'all')
            data, total = get_glossary_paginated('statistics_glossary', page, mode == 'starred')
            if 1 <= num <= len(data):
                idx, term, trans, definition, code, starred = data[num-1]
                text = f"📖 **{term}**\n🀄️ {trans}\n📝 {definition}"
                if code:
                    text += f"\n\n💻 程式碼：\n```\n{code}\n```"
                reply = TextMessage(text=text, quick_reply=get_course_quick_reply())
            else:
                reply = TextMessage(text="請輸入正確的編號", quick_reply=get_course_quick_reply())
        
        elif session.get('socio_page') is not None:
            page = session.get('socio_page', 1)
            mode = session.get('socio_mode', 'starred')
            data, total = get_glossary_paginated('sociology_glossary', page, mode == 'starred')
            if 1 <= num <= len(data):
                idx, term, trans, definition, code, starred = data[num-1]
                text = f"📖 **{term}**\n🀄️ {trans}\n📝 {definition}"
                reply = TextMessage(text=text, quick_reply=get_course_quick_reply())
            else:
                reply = TextMessage(text="請輸入正確的編號", quick_reply=get_course_quick_reply())
        
        elif session.get('outdoor_page') is not None:
            page = session.get('outdoor_page', 1)
            mode = session.get('outdoor_mode', 'all')
            data, total = get_glossary_paginated('outdoor_glossary', page, mode == 'starred')
            if 1 <= num <= len(data):
                idx, term, trans, definition, code, starred = data[num-1]
                text = f"📖 **{term}**\n🀄️ {trans}\n📝 {definition}"
                reply = TextMessage(text=text, quick_reply=get_course_quick_reply())
            else:
                reply = TextMessage(text="請輸入正確的編號", quick_reply=get_course_quick_reply())
        else:
            reply = TextMessage(text="請先選擇一個科目", quick_reply=get_main_quick_reply())
    
    # ========== 關鍵字查詢 ==========
    elif msg_lower.startswith("查 "):
        keyword = msg_lower[3:]
        found = False
        
        for table, name in [('statistics_glossary', '統計'), ('sociology_glossary', '社會學'), ('outdoor_glossary', '探索教育')]:
            results = search_glossary(table, keyword)
            if results:
                for idx, term, trans, definition, code in results:
                    text = f"📖 **{term}** ({name})\n🀄️ {trans}\n📝 {definition}"
                    if code:
                        text += f"\n\n💻 程式碼：\n```\n{code}\n```"
                    reply = TextMessage(text=text, quick_reply=get_course_quick_reply())
                    found = True
                    break
            if found:
                break
        
        if not found:
            reply = TextMessage(text=f"❌ 查無「{keyword}」\n\n試試：t-test, ANOVA, 運動社會化, 體驗式學習", quick_reply=get_course_quick_reply())
    
    # ========== 待辦事項 ==========
    elif msg_lower.startswith("新增 "):
        task = msg[3:]
        todo_date = datetime.now().strftime('%Y-%m-%d')
        conn = sqlite3.connect('course_bot.db')
        c = conn.cursor()
        c.execute("INSERT INTO todos (user_id, task, todo_date, created_at) VALUES (?, ?, ?, ?)",
                  (user_id, task, todo_date, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()
        conn.close()
        reply = TextMessage(text=f"✅ 已新增：{task}\n📅 日期：{todo_date}", quick_reply=get_main_quick_reply())
    
    elif msg_lower in ["待辦", "待辦事項", "todo"]:
        conn = sqlite3.connect('course_bot.db')
        c = conn.cursor()
        c.execute("SELECT id, task, todo_date FROM todos WHERE user_id = ? AND status = 'pending' ORDER BY todo_date LIMIT 20", (user_id,))
        todos = c.fetchall()
        conn.close()
        if todos:
            text = "✅ 待辦清單：\n"
            for tid, task, date_str in todos:
                text += f"{tid}. [{date_str}] {task}\n"
            text += "\n💡 完成請輸入「完成 編號」"
        else:
            text = "📋 沒有待辦事項\n\n💡 輸入「新增 買牛奶」新增"
        reply = TextMessage(text=text, quick_reply=get_main_quick_reply())
    
    elif msg_lower.startswith("完成 "):
        try:
            todo_id = int(msg_lower[3:])
            conn = sqlite3.connect('course_bot.db')
            c = conn.cursor()
            c.execute("UPDATE todos SET status = 'done' WHERE id = ? AND user_id = ?", (todo_id, user_id))
            conn.commit()
            conn.close()
            reply = TextMessage(text=f"✅ 已完成編號 {todo_id}", quick_reply=get_main_quick_reply())
        except:
            reply = TextMessage(text="請輸入：完成 1", quick_reply=get_main_quick_reply())
    
    # 預設回應（附帶按鈕）
    else:
        reply = TextMessage(
            text=f"你說了：「{msg}」\n\n📌 試試看點擊下方按鈕：\n\n或輸入以下指令：\n• 天氣 - 傳送位置\n• 單字 - 隨機英文單字\n• 課程 - 選科目\n• 統計 / 運動社會學 / 探索教育\n• 查 t-test\n• 新增 買牛奶",
            quick_reply=get_main_quick_reply()
        )
    
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(reply_token=event.reply_token, messages=[reply])
        )

# ========== 管理後台 ==========
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form['password'] == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect('/admin')
        return render_template_string(LOGIN_TEMPLATE, error="密碼錯誤！")
    return render_template_string(LOGIN_TEMPLATE, error=None)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect('/login')

@app.route('/admin')
@login_required
def admin_dashboard():
    return render_template_string(DASHBOARD_TEMPLATE)

# 通用管理函數
def get_table_info(table_type):
    tables = {
        'vocabulary': {'table': 'vocabulary', 'name': '英文單字', 'columns': ['word', 'meaning', 'example'], 'labels': ['單字', '意思', '例句']},
        'statistics': {'table': 'statistics_glossary', 'name': '統計專有名詞', 'columns': ['term', 'translation', 'definition', 'code', 'is_starred'], 'labels': ['英文/名詞', '中文翻譯', '解釋', '程式碼', '核心']},
        'sociology': {'table': 'sociology_glossary', 'name': '運動社會學', 'columns': ['term', 'translation', 'definition', 'is_starred'], 'labels': ['英文/名詞', '中文翻譯', '解釋', '核心']},
        'outdoor': {'table': 'outdoor_glossary', 'name': '探索教育', 'columns': ['term', 'translation', 'definition', 'is_starred'], 'labels': ['英文/名詞', '中文翻譯', '解釋', '核心']},
    }
    return tables.get(table_type)

@app.route('/admin/<table_type>')
@login_required
def admin_table(table_type):
    info = get_table_info(table_type)
    if not info:
        return redirect('/admin')
    
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute(f"SELECT id, * FROM {info['table']} ORDER BY id")
    data = c.fetchall()
    conn.close()
    return render_template_string(TABLE_TEMPLATE, data=data, info=info, table_type=table_type)

@app.route('/admin/add/<table_type>', methods=['POST'])
@login_required
def admin_add(table_type):
    info = get_table_info(table_type)
    if not info:
        return redirect('/admin')
    
    columns = info['columns']
    values = [request.form.get(col, '') for col in columns]
    
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    placeholders = ','.join(['?' for _ in columns])
    c.execute(f"INSERT INTO {info['table']} ({','.join(columns)}) VALUES ({placeholders})", values)
    conn.commit()
    conn.close()
    return redirect(f'/admin/{table_type}')

@app.route('/admin/edit/<table_type>/<int:id>', methods=['POST'])
@login_required
def admin_edit(table_type, id):
    info = get_table_info(table_type)
    if not info:
        return redirect('/admin')
    
    columns = info['columns']
    values = [request.form.get(col, '') for col in columns]
    values.append(id)
    
    set_clause = ','.join([f"{col}=?" for col in columns])
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute(f"UPDATE {info['table']} SET {set_clause} WHERE id = ?", values)
    conn.commit()
    conn.close()
    return redirect(f'/admin/{table_type}')

@app.route('/admin/delete/<table_type>/<int:id>')
@login_required
def admin_delete(table_type, id):
    info = get_table_info(table_type)
    if not info:
        return redirect('/admin')
    
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute(f"DELETE FROM {info['table']} WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return redirect(f'/admin/{table_type}')

@app.route('/admin/import_csv/<table_type>', methods=['POST'])
@login_required
def admin_import_csv(table_type):
    info = get_table_info(table_type)
    if not info:
        return redirect('/admin')
    
    if 'csv_file' not in request.files:
        return redirect(f'/admin/{table_type}')
    file = request.files['csv_file']
    if file.filename == '':
        return redirect(f'/admin/{table_type}')
    
    content = file.read().decode('utf-8')
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    columns = info['columns']
    
    for line in content.strip().split('\n'):
        parts = line.split(',')
        if len(parts) >= len(columns):
            values = parts[:len(columns)]
            placeholders = ','.join(['?' for _ in values])
            try:
                c.execute(f"INSERT INTO {info['table']} ({','.join(columns)}) VALUES ({placeholders})", values)
            except:
                pass
    conn.commit()
    conn.close()
    return redirect(f'/admin/{table_type}')

# ========== HTML 模板 ==========
LOGIN_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head><title>HANK EduMentor - 登入</title><meta charset="UTF-8"></head>
<body style="font-family: Arial; text-align: center; margin-top: 100px;">
    <h2>🔐 HANK EduMentor 管理後台</h2>
    <form method="post">
        <input type="password" name="password" placeholder="輸入密碼" style="padding: 10px; width: 200px;">
        <button type="submit" style="padding: 10px 20px;">登入</button>
    </form>
    {% if error %}<p style="color: red;">{{ error }}</p>{% endif %}
</body>
</html>
'''

DASHBOARD_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head><title>HANK EduMentor</title><meta charset="UTF-8"></head>
<body style="font-family: Arial; padding: 20px; background: #f5f5f5;">
    <div style="max-width: 800px; margin: 0 auto;">
        <h1 style="color: #2c3e50;">🤖 HANK EduMentor 管理後台</h1>
        <p><a href="/logout" style="color: red;">登出</a></p>
        <div style="display: grid; gap: 15px; margin-top: 30px;">
            <a href="/admin/vocabulary" style="display: block; padding: 15px; background: #3498db; color: white; text-decoration: none; border-radius: 8px;">📚 英文單字管理</a>
            <a href="/admin/statistics" style="display: block; padding: 15px; background: #2ecc71; color: white; text-decoration: none; border-radius: 8px;">📊 實驗設計與統計</a>
            <a href="/admin/sociology" style="display: block; padding: 15px; background: #e74c3c; color: white; text-decoration: none; border-radius: 8px;">⚽ 運動社會學</a>
            <a href="/admin/outdoor" style="display: block; padding: 15px; background: #f39c12; color: white; text-decoration: none; border-radius: 8px;">🏕️ 探索教育</a>
        </div>
    </div>
</body>
</html>
'''

TABLE_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head><title>{{ info.name }}管理</title><meta charset="UTF-8"></head>
<body style="font-family: Arial; padding: 20px;">
    <h1>{{ info.name }}管理</h1>
    <p><a href="/admin">← 返回首頁</a> | <a href="/logout">登出</a></p>
    
    <div style="margin: 20px 0; padding: 15px; background: #e8f5e9;">
        <h3>📤 匯入 CSV</h3>
        <form method="post" action="/admin/import_csv/{{ table_type }}" enctype="multipart/form-data">
            <input type="file" name="csv_file" accept=".csv" required>
            <button type="submit">匯入</button>
        </form>
        <p style="font-size: 12px;">格式：{{ ', '.join(info.labels) }}</p>
    </div>
    
    <div style="margin: 20px 0; padding: 15px; background: #f0f0f0;">
        <h3>➕ 手動新增</h3>
        <form method="post" action="/admin/add/{{ table_type }}">
            {% for label in info.labels %}
            <input type="text" name="{{ info.columns[loop.index0] }}" placeholder="{{ label }}" style="margin: 5px;">
            {% endfor %}
            <button type="submit">新增</button>
        </form>
    </div>
    
    <table border="1" cellpadding="8" style="border-collapse: collapse; width: 100%;">
        <tr><th>ID</th>{% for label in info.labels %}<th>{{ label }}</th>{% endfor %}<th>操作</th></tr>
        {% for row in data %}
        <tr>
            <form method="post" action="/admin/edit/{{ table_type }}/{{ row[0] }}">
                <td>{{ row[0] }}</td>
                {% for i in range(info.columns|length) %}
                <td><input type="text" name="{{ info.columns[i] }}" value="{{ row[i+1] }}" style="width: 100%;"></td>
                {% endfor %}
                <td>
                    <button type="submit">儲存</button>
                    <a href="/admin/delete/{{ table_type }}/{{ row[0] }}" onclick="return confirm('確定刪除？')">刪除</a>
                </td>
            </form>
        <tr>
        {% endfor %}
    </table>
</body>
</html>
'''

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
