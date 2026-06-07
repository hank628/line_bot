from flask import Flask, request, abort, render_template_string, redirect, session, jsonify
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, PushMessageRequest, TextMessage,
    QuickReply, QuickReplyItem, MessageAction
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, PostbackEvent, FollowEvent, LocationMessageContent
import os
from datetime import datetime, timedelta
import random
import requests
import sqlite3
import csv
import io
import re
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
from functools import wraps

# ========== 設定 ==========
CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
SECRET_KEY = os.environ.get("SECRET_KEY", "your-secret-key-here")

app = Flask(__name__)
app.secret_key = SECRET_KEY

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
    
    # 三個科目的專有名詞表
    c.execute('''CREATE TABLE IF NOT EXISTS glossary (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subject TEXT,
        term TEXT,
        translation TEXT,
        definition TEXT,
        code TEXT
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
            ("statistics", "統計學 📊", "Statistics is important for research."),
            ("sociology", "社會學 👥", "Sociology studies human society."),
            ("outdoor", "戶外探索 🏕️", "Outdoor education is fun."),
        ]
        c.executemany("INSERT INTO vocabulary (word, meaning, example) VALUES (?, ?, ?)", default_vocab)
    
    # 預設專有名詞
    c.execute("SELECT COUNT(*) FROM glossary")
    if c.fetchone()[0] == 0:
        default_glossary = [
            # 實驗設計與統計
            ("實驗設計與統計", "t-test", "t檢定", "比較兩組平均數差異", 
             "from scipy import stats\nt_stat, p_value = stats.ttest_ind(group1, group2)"),
            ("實驗設計與統計", "ANOVA", "變異數分析", "比較三組以上平均數差異",
             "from scipy import stats\nf_stat, p_value = stats.f_oneway(group1, group2, group3)"),
            ("實驗設計與統計", "correlation", "相關", "探討兩變數間關聯性",
             "from scipy import stats\nr, p_value = stats.pearsonr(x, y)"),
            ("實驗設計與統計", "regression", "迴歸", "預測與解釋變數關係",
             "from sklearn.linear_model import LinearRegression\nmodel = LinearRegression()\nmodel.fit(X, y)"),
            # 運動社會學
            ("運動社會學", "sports socialization", "運動社會化", "個人透過運動學習社會規範和價值觀的過程", ""),
            ("運動社會學", "social stratification", "社會階層化", "運動參與和成就受到社會階級影響的現象", ""),
            ("運動社會學", "gender ideology", "性別意識形態", "社會對男性和女性在運動中角色的期待和刻板印象", ""),
            ("運動社會學", "sports fan", "運動迷", "對特定運動隊伍或運動員有強烈認同和支持的人", ""),
            # 探索教育
            ("探索教育", "experiential learning", "體驗式學習", "透過直接經驗和反思來學習的循環過程", ""),
            ("探索教育", "challenge by choice", "自願挑戰", "參與者可自行決定是否參與及參與程度", ""),
            ("探索教育", "full value contract", "全價值契約", "團體成員共同建立的參與規範和承諾", ""),
            ("探索教育", "debriefing", "反思回饋", "活動後引導參與者分享和討論經驗的過程", ""),
        ]
        c.executemany("INSERT INTO glossary (subject, term, translation, definition, code) VALUES (?, ?, ?, ?, ?)", default_glossary)
    
    conn.commit()
    conn.close()

init_db()

# ========== 資料庫操作函數 ==========
def get_all_vocab():
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("SELECT id, word, meaning, example FROM vocabulary ORDER BY word")
    result = c.fetchall()
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

def delete_vocab(id):
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("DELETE FROM vocabulary WHERE id = ?", (id,))
    conn.commit()
    conn.close()

def import_vocab_csv(file_content):
    """匯入 CSV 格式：英文單字,中文意思,例句"""
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    success_count = 0
    error_count = 0
    
    try:
        reader = csv.reader(io.StringIO(file_content.decode('utf-8')))
        for row in reader:
            if len(row) >= 2:
                word = row[0].strip().lower()
                meaning = row[1].strip()
                example = row[2].strip() if len(row) > 2 else ""
                if word and meaning:
                    try:
                        c.execute("INSERT INTO vocabulary (word, meaning, example) VALUES (?, ?, ?)", 
                                  (word, meaning, example))
                        success_count += 1
                    except sqlite3.IntegrityError:
                        error_count += 1
    except Exception as e:
        print(f"匯入錯誤: {e}")
        error_count += 1
    
    conn.commit()
    conn.close()
    return success_count, error_count

def get_glossary(subject, term=None):
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    if term:
        c.execute("SELECT term, translation, definition, code FROM glossary WHERE subject = ? AND term LIKE ?", 
                  (subject, f'%{term}%'))
    else:
        c.execute("SELECT term, translation, definition, code FROM glossary WHERE subject = ?", (subject,))
    result = c.fetchall()
    conn.close()
    return result

def add_glossary(subject, term, translation, definition, code=""):
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    try:
        c.execute("INSERT INTO glossary (subject, term, translation, definition, code) VALUES (?, ?, ?, ?, ?)",
                  (subject, term, translation, definition, code))
        conn.commit()
        success = True
    except:
        success = False
    conn.close()
    return success

def delete_glossary(id):
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("DELETE FROM glossary WHERE id = ?", (id,))
    conn.commit()
    conn.close()

def import_glossary_csv(file_content, subject):
    """匯入專有名詞 CSV：英文,中文,解釋,程式碼"""
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    success_count = 0
    error_count = 0
    
    try:
        reader = csv.reader(io.StringIO(file_content.decode('utf-8')))
        for row in reader:
            if len(row) >= 3:
                term = row[0].strip()
                translation = row[1].strip()
                definition = row[2].strip()
                code = row[3].strip() if len(row) > 3 else ""
                if term and translation:
                    try:
                        c.execute("INSERT INTO glossary (subject, term, translation, definition, code) VALUES (?, ?, ?, ?, ?)",
                                  (subject, term, translation, definition, code))
                        success_count += 1
                    except:
                        error_count += 1
    except Exception as e:
        error_count += 1
    
    conn.commit()
    conn.close()
    return success_count, error_count

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

def register_user(user_id):
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, created_at) VALUES (?, ?)",
              (user_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE push_enabled = 1")
    result = [row[0] for row in c.fetchall()]
    conn.close()
    return result

# ========== 天氣功能（修正版）==========
def get_weather_by_coords(lat, lon):
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true&temperature_unit=celsius&timezone=Asia/Taipei"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            temp = data['current_weather']['temperature']
            weather_code = data['current_weather']['weathercode']
            weather_map = {
                0: "☀️ 晴", 1: "🌤️ 大致晴朗", 2: "⛅ 局部多雲", 3: "☁️ 陰",
                45: "🌫️ 霧", 48: "🌫️ 濃霧", 51: "🌦️ 毛毛雨", 53: "🌦️ 毛毛雨",
                55: "🌦️ 毛毛雨", 61: "🌧️ 雨", 63: "🌧️ 雨", 65: "🌧️ 大雨",
                71: "❄️ 雪", 73: "❄️ 雪", 75: "❄️ 大雪", 95: "⛈️ 雷雨"
            }
            weather = weather_map.get(weather_code, "🌡️ 未知")
            return f"{weather}，{temp}°C"
        else:
            return f"天氣API回應異常 (狀態碼:{r.status_code})"
    except requests.exceptions.Timeout:
        return "天氣服務連線逾時，請稍後再試"
    except Exception as e:
        return f"天氣資料暫時無法取得 ({str(e)})"

def get_city_from_coords(lat, lon):
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

# ========== 常駐按鈕（每則回覆都附帶）==========
def get_quick_reply_buttons():
    """取得常駐按鈕（用於每則回覆）"""
    return QuickReply(
        items=[
            QuickReplyItem(action=MessageAction(label="🌤️天氣", text="天氣")),
            QuickReplyItem(action=MessageAction(label="📚英字", text="單字")),
            QuickReplyItem(action=MessageAction(label="📊統計", text="實驗設計與統計")),
            QuickReplyItem(action=MessageAction(label="⚽社會", text="運動社會學")),
            QuickReplyItem(action=MessageAction(label="🏕️探索", text="探索教育")),
            QuickReplyItem(action=MessageAction(label="✅待辦", text="待辦")),
        ]
    )

def create_main_menu():
    """主選單（含按鈕）"""
    return TextMessage(
        text="🤖 課程小幫手\n\n請選擇功能：",
        quick_reply=get_quick_reply_buttons()
    )

# ========== 科目查詢函數 ==========
def search_glossary(subject, keyword=None):
    """查詢科目專有名詞"""
    results = get_glossary(subject, keyword)
    if not results:
        return None
    
    if keyword and len(results) > 0:
        # 單一查詢結果
        term, translation, definition, code = results[0]
        text = f"📖 **{term}**\n"
        text += f"🀄️ {translation}\n"
        text += f"📝 {definition}\n"
        if code:
            text += f"\n```python\n{code}\n```"
        return text
    elif len(results) > 0:
        # 列出所有名詞
        text = f"📚 **{subject} 專有名詞**\n\n"
        for term, translation, definition, code in results[:20]:
            text += f"• **{term}** - {translation}\n"
        text += "\n💡 輸入「查 [名詞]」可看詳細解釋"
        return text
    return None

# ========== 推播功能 ==========
def push_todos():
    tz = pytz.timezone('Asia/Taipei')
    now = datetime.now(tz)
    
    if now.hour == 7:
        title = "🌅 早安！今天的待辦事項："
        date_str = now.strftime('%Y-%m-%d')
    elif now.hour == 21:
        title = "🌙 晚安！明天的待辦事項："
        tomorrow = now + timedelta(days=1)
        date_str = tomorrow.strftime('%Y-%m-%d')
    else:
        return
    
    users = get_all_users()
    for user_id in users:
        todos = get_todos_by_date(user_id, date_str)
        if todos:
            todo_list = "\n".join([f"{i+1}. {task}" for i, (_, task) in enumerate(todos)])
            message = f"{title}\n\n{todo_list}"
        else:
            message = f"{title}\n\n📋 目前沒有待辦事項"
        
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
scheduler.add_job(push_todos, CronTrigger(hour=7, minute=0))
scheduler.add_job(push_todos, CronTrigger(hour=21, minute=0))
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
    
    reply = TextMessage(
        text=f"📍 {city}\n🌡️ {weather}\n\n💡 試試其他功能：",
        quick_reply=get_quick_reply_buttons()
    )
    
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
    register_user(user_id)
    
    # 主選單
    if msg_lower in ["選單", "功能", "幫助", "menu"]:
        reply = create_main_menu()
    
    # 天氣引導
    elif msg_lower in ["天氣", "weather"]:
        reply = TextMessage(
            text="📍 如何取得天氣？\n\n1️⃣ 點選聊天室左下角的「＋」\n2️⃣ 選擇「位置」\n3️⃣ 點選「傳送目前位置」\n\n收到位置後就會告訴你當地天氣！",
            quick_reply=get_quick_reply_buttons()
        )
    
    # 三個科目主選單
    elif msg_lower in ["實驗設計與統計", "統計", "實驗設計"]:
        result = search_glossary("實驗設計與統計")
        if result:
            reply = TextMessage(text=result, quick_reply=get_quick_reply_buttons())
        else:
            reply = TextMessage(text="📊 實驗設計與統計\n\n輸入「查 t-test」可查詢專有名詞", quick_reply=get_quick_reply_buttons())
    
    elif msg_lower in ["運動社會學", "社會學", "運動"]:
        result = search_glossary("運動社會學")
        if result:
            reply = TextMessage(text=result, quick_reply=get_quick_reply_buttons())
        else:
            reply = TextMessage(text="⚽ 運動社會學\n\n輸入「查 運動社會化」可查詢專有名詞", quick_reply=get_quick_reply_buttons())
    
    elif msg_lower in ["探索教育", "探索", "戶外"]:
        result = search_glossary("探索教育")
        if result:
            reply = TextMessage(text=result, quick_reply=get_quick_reply_buttons())
        else:
            reply = TextMessage(text="🏕️ 探索教育\n\n輸入「查 體驗式學習」可查詢專有名詞", quick_reply=get_quick_reply_buttons())
    
    # 查詢專有名詞
    elif msg_lower.startswith("查 "):
        keyword = msg_lower[3:]
        # 依序查三個科目
        for subject in ["實驗設計與統計", "運動社會學", "探索教育"]:
            results = get_glossary(subject, keyword)
            if results:
                term, translation, definition, code = results[0]
                text = f"📖 **{term}**\n"
                text += f"🀄️ {translation}\n"
                text += f"📝 {definition}\n"
                if code:
                    text += f"\n💻 程式碼：\n```\n{code}\n```"
                reply = TextMessage(text=text, quick_reply=get_quick_reply_buttons())
                break
        else:
            reply = TextMessage(text=f"❌ 查無「{keyword}」\n\n試試：t-test, ANOVA, 運動社會化, 體驗式學習", quick_reply=get_quick_reply_buttons())
    
    # 英文單字
    elif msg_lower == "單字":
        conn = sqlite3.connect('course_bot.db')
        c = conn.cursor()
        c.execute("SELECT word, meaning FROM vocabulary ORDER BY RANDOM() LIMIT 1")
        result = c.fetchone()
        conn.close()
        if result:
            word, meaning = result
            reply = TextMessage(text=f"📖 今日單字：{word} = {meaning}", quick_reply=get_quick_reply_buttons())
        else:
            reply = TextMessage(text="📖 暫時沒有單字資料", quick_reply=get_quick_reply_buttons())
    
    # 待辦事項
    elif msg_lower.startswith("新增 "):
        task_part = msg[3:]
        todo_date = None
        task = task_part
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', task_part)
        if date_match:
            todo_date = date_match.group(1)
            task = task_part.replace(todo_date, '').strip()
        if not task:
            task = "待辦事項"
        add_todo(user_id, task, todo_date)
        date_str = todo_date if todo_date else "今天"
        reply = TextMessage(text=f"✅ 已新增：{task}\n📅 日期：{date_str}", quick_reply=get_quick_reply_buttons())
    
    elif msg_lower in ["待辦", "待辦事項", "todo"]:
        todos = get_all_todos(user_id)
        if todos:
            text = "✅ 待辦清單：\n"
            for tid, task, date_str in todos:
                text += f"{tid}. [{date_str}] {task}\n"
            text += "\n💡 完成請輸入「完成 編號」"
        else:
            text = "📋 沒有待辦事項\n\n💡 新增：新增 買牛奶\n💡 指定日期：新增 交作業 2026-06-15"
        reply = TextMessage(text=text, quick_reply=get_quick_reply_buttons())
    
    elif msg_lower.startswith("完成 "):
        try:
            todo_id = int(msg_lower[3:])
            if complete_todo(user_id, todo_id):
                reply = TextMessage(text=f"✅ 已完成編號 {todo_id}", quick_reply=get_quick_reply_buttons())
            else:
                reply = TextMessage(text="❌ 找不到該編號", quick_reply=get_quick_reply_buttons())
        except:
            reply = TextMessage(text="請輸入：完成 1", quick_reply=get_quick_reply_buttons())
    
    # 預設回覆（附帶按鈕）
    else:
        reply = TextMessage(
            text=f"你說了：「{msg}」\n\n📌 試試看：\n• 實驗設計與統計\n• 運動社會學\n• 探索教育\n• 查 t-test\n• 新增 買牛奶",
            quick_reply=get_quick_reply_buttons()
        )
    
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(reply_token=event.reply_token, messages=[reply])
        )

# ========== Web 管理後台 ==========
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
            return redirect('/')
        else:
            return render_template_string(LOGIN_TEMPLATE, error="密碼錯誤！")
    return render_template_string(LOGIN_TEMPLATE, error=None)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect('/login')

@app.route('/')
def index():
    if session.get('logged_in'):
        return render_template_string(DASHBOARD_TEMPLATE)
    return redirect('/login')

# 單字管理
@app.route('/vocabulary')
@login_required
def vocabulary_page():
    data = get_all_vocab()
    return render_template_string(VOCAB_TEMPLATE, data=data)

@app.route('/add_vocab', methods=['POST'])
@login_required
def add_vocab_route():
    word = request.form['word']
    meaning = request.form['meaning']
    example = request.form.get('example', '')
    add_vocab(word, meaning, example)
    return redirect('/vocabulary')

@app.route('/delete_vocab/<int:id>')
@login_required
def delete_vocab_route(id):
    delete_vocab(id)
    return redirect('/vocabulary')

@app.route('/import_vocab_csv', methods=['POST'])
@login_required
def import_vocab_csv_route():
    if 'csv_file' not in request.files:
        return redirect('/vocabulary')
    file = request.files['csv_file']
    if file.filename == '':
        return redirect('/vocabulary')
    if file:
        content = file.read()
        success, error = import_vocab_csv(content)
        return redirect('/vocabulary')

# 專有名詞管理
@app.route('/glossary/<subject>')
@login_required
def glossary_page(subject):
    data = get_glossary(subject)
    return render_template_string(GLOSSARY_TEMPLATE, data=data, subject=subject)

@app.route('/add_glossary', methods=['POST'])
@login_required
def add_glossary_route():
    subject = request.form['subject']
    term = request.form['term']
    translation = request.form['translation']
    definition = request.form['definition']
    code = request.form.get('code', '')
    add_glossary(subject, term, translation, definition, code)
    return redirect(f'/glossary/{subject}')

@app.route('/delete_glossary/<int:id>/<subject>')
@login_required
def delete_glossary_route(id, subject):
    delete_glossary(id)
    return redirect(f'/glossary/{subject}')

@app.route('/import_glossary_csv', methods=['POST'])
@login_required
def import_glossary_csv_route():
    subject = request.form['subject']
    if 'csv_file' not in request.files:
        return redirect(f'/glossary/{subject}')
    file = request.files['csv_file']
    if file.filename == '':
        return redirect(f'/glossary/{subject}')
    if file:
        content = file.read()
        success, error = import_glossary_csv(content, subject)
        return redirect(f'/glossary/{subject}')

# ========== HTML 模板 ==========
LOGIN_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head><title>課程小幫手 - 登入</title><meta charset="UTF-8"></head>
<body style="font-family: Arial; text-align: center; margin-top: 100px;">
    <h2>🔐 管理後台登入</h2>
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
<head><title>課程小幫手</title><meta charset="UTF-8"></head>
<body style="font-family: Arial; padding: 20px;">
    <h1>🤖 課程小幫手 管理後台</h1>
    <p><a href="/logout">登出</a></p>
    <ul style="font-size: 18px; line-height: 2;">
        <li><a href="/vocabulary">📚 管理英文單字</a></li>
        <li><a href="/glossary/實驗設計與統計">📊 實驗設計與統計 - 專有名詞</a></li>
        <li><a href="/glossary/運動社會學">⚽ 運動社會學 - 專有名詞</a></li>
        <li><a href="/glossary/探索教育">🏕️ 探索教育 - 專有名詞</a></li>
    </ul>
</body>
</html>
'''

VOCAB_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head><title>管理單字</title><meta charset="UTF-8"></head>
<body style="font-family: Arial; padding: 20px;">
    <h1>📚 英文單字管理</h1>
    <p><a href="/">← 返回首頁</a> | <a href="/logout">登出</a></p>
    
    <div style="margin: 20px 0; padding: 15px; background: #e8f5e9;">
        <h3>📤 匯入 CSV 檔案</h3>
        <form method="post" action="/import_vocab_csv" enctype="multipart/form-data">
            <input type="file" name="csv_file" accept=".csv" required>
            <button type="submit">匯入</button>
        </form>
        <p style="font-size: 12px; color: #666;">CSV 格式：英文單字,中文意思,例句 (每行一筆)</p>
    </div>
    
    <div style="margin: 20px 0; padding: 15px; background: #f0f0f0;">
        <h3>➕ 手動新增</h3>
        <form method="post" action="/add_vocab">
            <input type="text" name="word" placeholder="英文單字" required>
            <input type="text" name="meaning" placeholder="中文意思" required>
            <input type="text" name="example" placeholder="例句 (選填)" style="width: 300px;">
            <button type="submit">新增</button>
        </form>
    </div>
    
    <table border="1" cellpadding="8" style="border-collapse: collapse;">
        <tr><th>ID</th><th>單字</th><th>意思</th><th>例句</th><th>操作</th></tr>
        {% for row in data %}
        <tr>
            <td>{{ row[0] }}</td>
            <td><strong>{{ row[1] }}</strong></td>
            <td>{{ row[2] }}</td>
            <td>{{ row[3] }}</td>
            <td><a href="/delete_vocab/{{ row[0] }}" onclick="return confirm('確定刪除？')">刪除</a></td>
        </tr>
        {% endfor %}
    </table>
</body>
</html>
'''

GLOSSARY_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head><title>管理專有名詞 - {{ subject }}</title><meta charset="UTF-8"></head>
<body style="font-family: Arial; padding: 20px;">
    <h1>📖 {{ subject }} - 專有名詞管理</h1>
    <p><a href="/">← 返回首頁</a> | <a href="/logout">登出</a></p>
    
    <div style="margin: 20px 0; padding: 15px; background: #e8f5e9;">
        <h3>📤 匯入 CSV 檔案</h3>
        <form method="post" action="/import_glossary_csv" enctype="multipart/form-data">
            <input type="hidden" name="subject" value="{{ subject }}">
            <input type="file" name="csv_file" accept=".csv" required>
            <button type="submit">匯入</button>
        </form>
        <p style="font-size: 12px; color: #666;">CSV 格式：英文/中文,中文,解釋,程式碼 (每行一筆)</p>
    </div>
    
    <div style="margin: 20px 0; padding: 15px; background: #f0f0f0;">
        <h3>➕ 手動新增</h3>
        <form method="post" action="/add_glossary">
            <input type="hidden" name="subject" value="{{ subject }}">
            <input type="text" name="term" placeholder="英文/中文" required style="width: 200px;">
            <input type="text" name="translation" placeholder="翻譯" required style="width: 150px;">
            <input type="text" name="definition" placeholder="解釋" required style="width: 300px;">
            <textarea name="code" placeholder="程式碼 (選填)" rows="2" style="width: 400px;"></textarea>
            <button type="submit">新增</button>
        </form>
    </div>
    
    <table border="1" cellpadding="8" style="border-collapse: collapse; width: 100%;">
        <tr><th>ID</th><th>英文/中文</th><th>翻譯</th><th>解釋</th><th>程式碼</th><th>操作</th></tr>
        {% for row in data %}
        <tr>
            <td>{{ row[0] }}</td>
            <td><strong>{{ row[1] }}</strong></td>
            <td>{{ row[2] }}</td>
            <td>{{ row[3][:50] }}{% if row[3]|length > 50 %}...{% endif %}</td>
            <td>{{ row[4][:30] if row[4] else '' }}</td>
            <td><a href="/delete_glossary/{{ row[0] }}/{{ subject }}" onclick="return confirm('確定刪除？')">刪除</a></td>
        </tr>
        {% endfor %}
    </table>
</body>
</html>
'''

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True)
