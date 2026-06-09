from flask import Flask, request, abort, render_template_string, redirect, session, Response
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, PushMessageRequest, TextMessage,
    QuickReply, QuickReplyItem, MessageAction
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, FollowEvent
import os
import sqlite3
import requests
import random
import csv
import io
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
TEACHER_USER_ID = os.environ.get("TEACHER_USER_ID", "")

app = Flask(__name__)
app.secret_key = SECRET_KEY

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# ========== 防重複推播記錄 ==========
last_push_record = {}  # 記錄每天每時段是否已推播

# ========== 初始化資料庫 ==========
def init_db():
    import os
    db_path = 'course_bot.db'
    
    need_rebuild = False
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        try:
            c.execute("SELECT COUNT(*) FROM glossary_socio")
        except:
            need_rebuild = True
        conn.close()
    
    if need_rebuild or not os.path.exists(db_path):
        if os.path.exists(db_path):
            os.remove(db_path)
            print("✅ 已刪除舊資料庫")
        
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        
        c.execute('''CREATE TABLE vocabulary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT UNIQUE,
            meaning TEXT
        )''')
        
        c.execute('''CREATE TABLE glossary_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            term TEXT UNIQUE,
            translation TEXT,
            definition TEXT,
            code TEXT,
            is_starred INTEGER DEFAULT 0
        )''')
        
        c.execute('''CREATE TABLE glossary_socio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            term TEXT UNIQUE,
            translation TEXT,
            definition TEXT,
            is_starred INTEGER DEFAULT 0
        )''')
        
        c.execute('''CREATE TABLE glossary_outdoor (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            term TEXT UNIQUE,
            translation TEXT,
            definition TEXT,
            is_starred INTEGER DEFAULT 0
        )''')
        
        c.execute('''CREATE TABLE student_todos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            task TEXT,
            todo_date TEXT,
            created_at TEXT,
            status TEXT DEFAULT 'pending'
        )''')
        
        c.execute('''CREATE TABLE teacher_todos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task TEXT,
            todo_date TEXT,
            todo_time TEXT,
            created_at TEXT,
            status TEXT DEFAULT 'pending'
        )''')
        
        c.execute('''CREATE TABLE class_todos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task TEXT,
            todo_date TEXT,
            todo_time TEXT,
            created_at TEXT,
            status TEXT DEFAULT 'pending'
        )''')
        
        c.execute('''CREATE TABLE users (
            user_id TEXT PRIMARY KEY,
            created_at TEXT
        )''')
        
        # 預設英文單字
        default_vocab = [
            ("apple", "蘋果 🍎"),
            ("book", "書 📚"),
            ("computer", "電腦 💻"),
            ("teacher", "老師 👩‍🏫"),
            ("student", "學生 🧑‍🎓"),
        ]
        c.executemany("INSERT INTO vocabulary (word, meaning) VALUES (?, ?)", default_vocab)
        print("✅ 已寫入英文單字")
        
        # 預設統計名詞
        default_stats = [
            ("t-test", "t檢定", "比較兩組樣本平均數是否有顯著差異", 
             "from scipy import stats\nimport numpy as np\n\ngroup1 = [85, 88, 90, 92, 86]\ngroup2 = [78, 82, 80, 85, 79]\n\nt_stat, p_value = stats.ttest_ind(group1, group2)\n\nprint(f't值: {t_stat:.4f}')\nprint(f'p值: {p_value:.4f}')", 1),
            ("ANOVA", "變異數分析", "比較三組以上樣本平均數是否有顯著差異", 
             "from scipy import stats\n\ngroup1 = [85, 88, 90, 92, 86]\ngroup2 = [78, 82, 80, 85, 79]\ngroup3 = [75, 78, 76, 80, 77]\n\nf_stat, p_value = stats.f_oneway(group1, group2, group3)", 1),
            ("correlation", "相關分析", "探討兩個連續變數之間的線性關係強度", 
             "from scipy import stats\n\nx = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]\ny = [2, 4, 6, 8, 10, 12, 14, 16, 18, 20]\n\nr, p_value = stats.pearsonr(x, y)", 1),
        ]
        c.executemany("INSERT INTO glossary_stats (term, translation, definition, code, is_starred) VALUES (?, ?, ?, ?, ?)", default_stats)
        print("✅ 已寫入統計名詞")
        
        # 預設社會學名詞
        default_socio = [
            ("sports socialization", "運動社會化", "個人透過運動參與學習社會規範、價值觀和行為模式的過程", 1),
            ("social stratification", "社會階層化", "社會依據財富、權力、聲望等資源將人群分層的現象", 1),
            ("gender ideology", "性別意識形態", "社會對男性與女性在運動中應有的角色、行為和價值的期待", 1),
            ("sports fan", "運動迷", "對特定運動隊伍、運動員或運動項目有強烈情感認同和支持的人", 1),
        ]
        c.executemany("INSERT INTO glossary_socio (term, translation, definition, is_starred) VALUES (?, ?, ?, ?)", default_socio)
        print("✅ 已寫入社會學名詞")
        
        # 預設探索教育名詞
        default_outdoor = [
            ("experiential learning", "體驗式學習", "透過直接經驗和反思來學習的循環過程", 1),
            ("challenge by choice", "自願挑戰", "參與者可依自身意願決定是否參與及參與程度", 1),
            ("debriefing", "反思回饋", "活動結束後引導參與者分享經驗、感受和學習的結構化討論過程", 1),
        ]
        c.executemany("INSERT INTO glossary_outdoor (term, translation, definition, is_starred) VALUES (?, ?, ?, ?)", default_outdoor)
        print("✅ 已寫入探索教育名詞")
        
        conn.commit()
        
        c.execute("SELECT COUNT(*) FROM vocabulary")
        print(f"📖 英文單字筆數: {c.fetchone()[0]}")
        c.execute("SELECT COUNT(*) FROM glossary_stats")
        print(f"📊 統計名詞筆數: {c.fetchone()[0]}")
        c.execute("SELECT COUNT(*) FROM glossary_socio")
        print(f"⚽ 社會學名詞筆數: {c.fetchone()[0]}")
        c.execute("SELECT COUNT(*) FROM glossary_outdoor")
        print(f"🏕️ 探索教育名詞筆數: {c.fetchone()[0]}")
        
        conn.close()
        print("✅ 資料庫初始化完成")
    else:
        print("✅ 資料庫已存在，跳過初始化")

init_db()

# ========== 5個常駐按鈕選單 ==========
def get_main_quick_reply():
    return QuickReply(
        items=[
            QuickReplyItem(action=MessageAction(label="📚英字", text="單字")),
            QuickReplyItem(action=MessageAction(label="📊統計", text="統計")),
            QuickReplyItem(action=MessageAction(label="⚽社會", text="社會學")),
            QuickReplyItem(action=MessageAction(label="🏕️探索", text="探索")),
            QuickReplyItem(action=MessageAction(label="✅待辦", text="待辦")),
        ]
    )

# ========== 查詢函數 ==========
PAGE_SIZE = 10

def get_stats_list(page=1):
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    offset = (page - 1) * PAGE_SIZE
    c.execute("SELECT id, term, translation FROM glossary_stats ORDER BY id LIMIT ? OFFSET ?", (PAGE_SIZE, offset))
    results = c.fetchall()
    total = c.execute("SELECT COUNT(*) FROM glossary_stats").fetchone()[0]
    conn.close()
    return results, total

def get_stats_by_id(term_id):
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("SELECT term, translation, definition, code FROM glossary_stats WHERE id = ?", (term_id,))
    result = c.fetchone()
    conn.close()
    return result

def get_socio_list(page=1):
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    offset = (page - 1) * PAGE_SIZE
    c.execute("SELECT id, term, translation FROM glossary_socio ORDER BY id LIMIT ? OFFSET ?", (PAGE_SIZE, offset))
    results = c.fetchall()
    total = c.execute("SELECT COUNT(*) FROM glossary_socio").fetchone()[0]
    conn.close()
    return results, total

def get_socio_by_id(term_id):
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("SELECT term, translation, definition FROM glossary_socio WHERE id = ?", (term_id,))
    result = c.fetchone()
    conn.close()
    return result

def get_outdoor_list(page=1):
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    offset = (page - 1) * PAGE_SIZE
    c.execute("SELECT id, term, translation FROM glossary_outdoor ORDER BY id LIMIT ? OFFSET ?", (PAGE_SIZE, offset))
    results = c.fetchall()
    total = c.execute("SELECT COUNT(*) FROM glossary_outdoor").fetchone()[0]
    conn.close()
    return results, total

def get_outdoor_by_id(term_id):
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("SELECT term, translation, definition FROM glossary_outdoor WHERE id = ?", (term_id,))
    result = c.fetchone()
    conn.close()
    return result

def get_random_vocab(count=5):
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("SELECT word, meaning FROM vocabulary ORDER BY RANDOM() LIMIT ?", (count,))
    results = c.fetchall()
    conn.close()
    return results

# ========== 待辦推播（每分鐘檢查，防重複）==========
def push_todos():
    global last_push_record
    
    tz = pytz.timezone('Asia/Taipei')
    now = datetime.now(tz)
    today_str = now.strftime('%Y-%m-%d')
    now_time = now.strftime('%H:%M')
    
    # 清理過期的推播記錄（超過1天的刪除）
    keys_to_delete = []
    for key in last_push_record:
        if key.startswith(today_str):
            continue
        keys_to_delete.append(key)
    for key in keys_to_delete:
        del last_push_record[key]
    
    # 記錄當天是否已執行過的 key
    morning_key = f"{today_str}_morning"
    evening_key = f"{today_str}_evening"
    teacher_key = f"{today_str}_teacher"
    class_key = f"{today_str}_class"
    
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    
    # 1. 老師個人待辦推播（只要有符合條件就推，但同一天只推一次）
    if TEACHER_USER_ID and not last_push_record.get(teacher_key, False):
        c.execute("SELECT id, task FROM teacher_todos WHERE todo_date = ? AND todo_time <= ? AND status = 'pending'", (today_str, now_time))
        teacher_todos = c.fetchall()
        if teacher_todos:
            last_push_record[teacher_key] = True
            for tid, task in teacher_todos:
                try:
                    with ApiClient(configuration) as api_client:
                        line_bot_api = MessagingApi(api_client)
                        line_bot_api.push_message(PushMessageRequest(to=TEACHER_USER_ID, messages=[TextMessage(text=f"👨‍🏫 老師待辦提醒：{task}")]))
                    c.execute("UPDATE teacher_todos SET status = 'done' WHERE id = ?", (tid,))
                except Exception as e:
                    print(f"老師待辦推播失敗: {e}")
    
    # 2. 全班共同待辦推播
    if not last_push_record.get(class_key, False):
        c.execute("SELECT id, task FROM class_todos WHERE todo_date = ? AND todo_time <= ? AND status = 'pending'", (today_str, now_time))
        class_todos = c.fetchall()
        if class_todos:
            last_push_record[class_key] = True
            c.execute("SELECT user_id FROM users")
            users = [row[0] for row in c.fetchall()]
            for user_id in users:
                for tid, task in class_todos:
                    try:
                        with ApiClient(configuration) as api_client:
                            line_bot_api = MessagingApi(api_client)
                            line_bot_api.push_message(PushMessageRequest(to=user_id, messages=[TextMessage(text=f"📢 全班公告：{task}")]))
                    except Exception as e:
                        print(f"推播失敗 {user_id}: {e}")
            for tid, task in class_todos:
                c.execute("UPDATE class_todos SET status = 'done' WHERE id = ?", (tid,))
    
    # 3. 學生個人待辦推播（早上7點時段和晚上9點時段）
    # 早上時段：7:00 - 7:05
    if now.hour == 7 and now.minute <= 5 and not last_push_record.get(morning_key, False):
        last_push_record[morning_key] = True
        title = "🌅 早安！今天的待辦事項："
        date_str = today_str
        
        c.execute("SELECT user_id FROM users")
        users = [row[0] for row in c.fetchall()]
        
        for user_id in users:
            c.execute("SELECT id, task FROM student_todos WHERE user_id = ? AND todo_date = ? AND status = 'pending'", (user_id, date_str))
            todos = c.fetchall()
            if todos:
                todo_list = "\n".join([f"{i+1}. {task}" for i, (_, task) in enumerate(todos)])
                message = f"{title}\n\n{todo_list}"
                try:
                    with ApiClient(configuration) as api_client:
                        line_bot_api = MessagingApi(api_client)
                        line_bot_api.push_message(PushMessageRequest(to=user_id, messages=[TextMessage(text=message)]))
                except Exception as e:
                    print(f"推播失敗 {user_id}: {e}")
    
    # 晚上時段：21:00 - 21:05
    if now.hour == 21 and now.minute <= 5 and not last_push_record.get(evening_key, False):
        last_push_record[evening_key] = True
        title = "🌙 晚安！明天的待辦事項："
        date_str = (now + timedelta(days=1)).strftime('%Y-%m-%d')
        
        c.execute("SELECT user_id FROM users")
        users = [row[0] for row in c.fetchall()]
        
        for user_id in users:
            c.execute("SELECT id, task FROM student_todos WHERE user_id = ? AND todo_date = ? AND status = 'pending'", (user_id, date_str))
            todos = c.fetchall()
            if todos:
                todo_list = "\n".join([f"{i+1}. {task}" for i, (_, task) in enumerate(todos)])
                message = f"{title}\n\n{todo_list}"
                try:
                    with ApiClient(configuration) as api_client:
                        line_bot_api = MessagingApi(api_client)
                        line_bot_api.push_message(PushMessageRequest(to=user_id, messages=[TextMessage(text=message)]))
                except Exception as e:
                    print(f"推播失敗 {user_id}: {e}")
    
    conn.commit()
    conn.close()

# ========== 啟動排程（每分鐘檢查）==========
scheduler = BackgroundScheduler(timezone='Asia/Taipei')
scheduler.add_job(push_todos, CronTrigger(minute='*'))
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
    
    welcome_text = "🤖 歡迎使用 HANK EduMentor！\n\n📌 點擊下方按鈕：\n• 📚英字 - 隨機5個英文單字\n• 📊統計 - 查看統計名詞\n• ⚽社會 - 查看社會學名詞\n• 🏕️探索 - 查看探索教育名詞\n• ✅待辦 - 管理待辦事項\n\n📝 查詢方式：\n• 統計 3 或 se3（查 ID）\n• 統計頁2（跳到第2頁）"
    
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=welcome_text, quick_reply=get_main_quick_reply())]
            )
        )

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    msg = event.message.text.strip()
    msg_lower = msg.lower()
    user_id = event.source.user_id
    
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, created_at) VALUES (?, ?)", 
              (user_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit()
    conn.close()
    
    is_teacher = (user_id == TEACHER_USER_ID)
    
    if msg_lower in ["幫助", "選單", "menu", "help"]:
        reply = TextMessage(text="🤖 請點擊下方按鈕：\n\n📝 查詢方式：\n• 統計 3 或 se3\n• 統計頁2（跳到第2頁）", quick_reply=get_main_quick_reply())
    
    elif msg_lower in ["單字", "english", "vocab"]:
        results = get_random_vocab(5)
        if results:
            text = "📖 今日單字\n\n"
            for word, meaning in results:
                text += f"• {word} = {meaning}\n"
            reply = TextMessage(text=text, quick_reply=get_main_quick_reply())
        else:
            reply = TextMessage(text="📖 暫無單字", quick_reply=get_main_quick_reply())
    
    # ========== 統計列表（頁碼）==========
    elif msg_lower == "統計":
        data, total = get_stats_list(1)
        total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
        
        if data:
            text = f"📊 統計專有名詞 (第1頁/共{total_pages}頁)\n\n"
            for i, (sid, term, trans) in enumerate(data, 1):
                text += f"{i}. {term} - {trans}\n"
            text += f"\n💡 查詢方式：\n• 輸入「統計 數字」或「se數字」查詳細\n• 輸入「統計頁數字」跳到指定頁（如：統計頁2）"
            reply = TextMessage(text=text, quick_reply=get_main_quick_reply())
        else:
            reply = TextMessage(text="📊 暫無統計資料", quick_reply=get_main_quick_reply())
    
    # ========== 統計頁碼跳轉 ==========
    elif msg_lower.startswith("統計頁") and len(msg_lower) > 3 and msg_lower[3:].isdigit():
        target_page = int(msg_lower[3:])
        if target_page < 1:
            target_page = 1
        data, total = get_stats_list(target_page)
        total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
        if target_page > total_pages:
            target_page = total_pages
            data, total = get_stats_list(target_page)
        
        if data:
            text = f"📊 統計專有名詞 (第{target_page}頁/共{total_pages}頁)\n\n"
            for i, (sid, term, trans) in enumerate(data, 1):
                text += f"{i}. {term} - {trans}\n"
            text += f"\n💡 查詢方式：\n• 輸入「統計 數字」或「se數字」查詳細\n• 輸入「統計頁數字」跳到指定頁"
            reply = TextMessage(text=text, quick_reply=get_main_quick_reply())
        else:
            reply = TextMessage(text="📊 暫無統計資料", quick_reply=get_main_quick_reply())
    
    # ========== 社會學列表（頁碼）==========
    elif msg_lower == "社會學":
        data, total = get_socio_list(1)
        total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
        
        if data:
            text = f"⚽ 運動社會學 (第1頁/共{total_pages}頁)\n\n"
            for i, (sid, term, trans) in enumerate(data, 1):
                text += f"{i}. {term} - {trans}\n"
            text += f"\n💡 查詢方式：\n• 輸入「社會學 數字」或「ss數字」查詳細\n• 輸入「社會學頁數字」跳到指定頁（如：社會學頁2）"
            reply = TextMessage(text=text, quick_reply=get_main_quick_reply())
        else:
            reply = TextMessage(text="⚽ 暫無社會學資料", quick_reply=get_main_quick_reply())
    
    # ========== 社會學頁碼跳轉 ==========
    elif msg_lower.startswith("社會學頁") and len(msg_lower) > 4 and msg_lower[4:].isdigit():
        target_page = int(msg_lower[4:])
        if target_page < 1:
            target_page = 1
        data, total = get_socio_list(target_page)
        total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
        if target_page > total_pages:
            target_page = total_pages
            data, total = get_socio_list(target_page)
        
        if data:
            text = f"⚽ 運動社會學 (第{target_page}頁/共{total_pages}頁)\n\n"
            for i, (sid, term, trans) in enumerate(data, 1):
                text += f"{i}. {term} - {trans}\n"
            text += f"\n💡 查詢方式：\n• 輸入「社會學 數字」或「ss數字」查詳細\n• 輸入「社會學頁數字」跳到指定頁"
            reply = TextMessage(text=text, quick_reply=get_main_quick_reply())
        else:
            reply = TextMessage(text="⚽ 暫無社會學資料", quick_reply=get_main_quick_reply())
    
    # ========== 探索教育列表（頁碼）==========
    elif msg_lower == "探索":
        data, total = get_outdoor_list(1)
        total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
        
        if data:
            text = f"🏕️ 探索教育 (第1頁/共{total_pages}頁)\n\n"
            for i, (sid, term, trans) in enumerate(data, 1):
                text += f"{i}. {term} - {trans}\n"
            text += f"\n💡 查詢方式：\n• 輸入「探索 數字」或「ae數字」查詳細\n• 輸入「探索頁數字」跳到指定頁（如：探索頁2）"
            reply = TextMessage(text=text, quick_reply=get_main_quick_reply())
        else:
            reply = TextMessage(text="🏕️ 暫無探索教育資料", quick_reply=get_main_quick_reply())
    
    # ========== 探索教育頁碼跳轉 ==========
    elif msg_lower.startswith("探索頁") and len(msg_lower) > 3 and msg_lower[3:].isdigit():
        target_page = int(msg_lower[3:])
        if target_page < 1:
            target_page = 1
        data, total = get_outdoor_list(target_page)
        total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
        if target_page > total_pages:
            target_page = total_pages
            data, total = get_outdoor_list(target_page)
        
        if data:
            text = f"🏕️ 探索教育 (第{target_page}頁/共{total_pages}頁)\n\n"
            for i, (sid, term, trans) in enumerate(data, 1):
                text += f"{i}. {term} - {trans}\n"
            text += f"\n💡 查詢方式：\n• 輸入「探索 數字」或「ae數字」查詳細\n• 輸入「探索頁數字」跳到指定頁"
            reply = TextMessage(text=text, quick_reply=get_main_quick_reply())
        else:
            reply = TextMessage(text="🏕️ 暫無探索教育資料", quick_reply=get_main_quick_reply())
    
    # ========== 快捷指令 ==========
    elif msg_lower.startswith("se") and len(msg_lower) > 2 and msg_lower[2:].isdigit():
        num = int(msg_lower[2:])
        detail = get_stats_by_id(num)
        if detail:
            term, trans, definition, code = detail
            text = f"📖 **{term}**\n🀄️ {trans}\n📝 {definition}"
            if code:
                text += f"\n\n💻 程式碼：\n```\n{code}\n```"
            reply = TextMessage(text=text, quick_reply=get_main_quick_reply())
        else:
            reply = TextMessage(text=f"❌ 查無 ID {num} 的統計名詞", quick_reply=get_main_quick_reply())
    
    elif msg_lower.startswith("ss") and len(msg_lower) > 2 and msg_lower[2:].isdigit():
        num = int(msg_lower[2:])
        detail = get_socio_by_id(num)
        if detail:
            term, trans, definition = detail
            text = f"📖 **{term}**\n🀄️ {trans}\n📝 {definition}"
            reply = TextMessage(text=text, quick_reply=get_main_quick_reply())
        else:
            reply = TextMessage(text=f"❌ 查無 ID {num} 的社會學名詞", quick_reply=get_main_quick_reply())
    
    elif msg_lower.startswith("ae") and len(msg_lower) > 2 and msg_lower[2:].isdigit():
        num = int(msg_lower[2:])
        detail = get_outdoor_by_id(num)
        if detail:
            term, trans, definition = detail
            text = f"📖 **{term}**\n🀄️ {trans}\n📝 {definition}"
            reply = TextMessage(text=text, quick_reply=get_main_quick_reply())
        else:
            reply = TextMessage(text=f"❌ 查無 ID {num} 的探索教育名詞", quick_reply=get_main_quick_reply())
    
    elif msg_lower.startswith("統計 ") and len(msg_lower) > 3:
        parts = msg_lower.split()
        if len(parts) == 2 and parts[1].isdigit():
            num = int(parts[1])
            detail = get_stats_by_id(num)
            if detail:
                term, trans, definition, code = detail
                text = f"📖 **{term}**\n🀄️ {trans}\n📝 {definition}"
                if code:
                    text += f"\n\n💻 程式碼：\n```\n{code}\n```"
                reply = TextMessage(text=text, quick_reply=get_main_quick_reply())
            else:
                reply = TextMessage(text=f"❌ 查無 ID {num} 的統計名詞", quick_reply=get_main_quick_reply())
        else:
            reply = TextMessage(text="請輸入「統計 數字」，例如：統計 1 或 se1", quick_reply=get_main_quick_reply())
    
    elif msg_lower.startswith("社會學 ") and len(msg_lower) > 4:
        parts = msg_lower.split()
        if len(parts) == 2 and parts[1].isdigit():
            num = int(parts[1])
            detail = get_socio_by_id(num)
            if detail:
                term, trans, definition = detail
                text = f"📖 **{term}**\n🀄️ {trans}\n📝 {definition}"
                reply = TextMessage(text=text, quick_reply=get_main_quick_reply())
            else:
                reply = TextMessage(text=f"❌ 查無 ID {num} 的社會學名詞", quick_reply=get_main_quick_reply())
        else:
            reply = TextMessage(text="請輸入「社會學 數字」，例如：社會學 1 或 ss1", quick_reply=get_main_quick_reply())
    
    elif msg_lower.startswith("探索 ") and len(msg_lower) > 3:
        parts = msg_lower.split()
        if len(parts) == 2 and parts[1].isdigit():
            num = int(parts[1])
            detail = get_outdoor_by_id(num)
            if detail:
                term, trans, definition = detail
                text = f"📖 **{term}**\n🀄️ {trans}\n📝 {definition}"
                reply = TextMessage(text=text, quick_reply=get_main_quick_reply())
            else:
                reply = TextMessage(text=f"❌ 查無 ID {num} 的探索教育名詞", quick_reply=get_main_quick_reply())
        else:
            reply = TextMessage(text="請輸入「探索 數字」，例如：探索 1 或 ae1", quick_reply=get_main_quick_reply())
    
    elif msg_lower.startswith("查 "):
        keyword = msg_lower[3:]
        
        conn = sqlite3.connect('course_bot.db')
        c = conn.cursor()
        c.execute("SELECT term, translation, definition, code FROM glossary_stats WHERE term LIKE ? OR translation LIKE ? LIMIT 1", (f'%{keyword}%', f'%{keyword}%'))
        result = c.fetchone()
        if result:
            term, trans, definition, code = result
            text = f"📖 **{term}** (統計)\n🀄️ {trans}\n📝 {definition}"
            if code:
                text += f"\n\n💻 程式碼：\n```\n{code}\n```"
            reply = TextMessage(text=text, quick_reply=get_main_quick_reply())
        else:
            c.execute("SELECT term, translation, definition FROM glossary_socio WHERE term LIKE ? OR translation LIKE ? LIMIT 1", (f'%{keyword}%', f'%{keyword}%'))
            result = c.fetchone()
            if result:
                term, trans, definition = result
                text = f"📖 **{term}** (社會學)\n🀄️ {trans}\n📝 {definition}"
                reply = TextMessage(text=text, quick_reply=get_main_quick_reply())
            else:
                c.execute("SELECT term, translation, definition FROM glossary_outdoor WHERE term LIKE ? OR translation LIKE ? LIMIT 1", (f'%{keyword}%', f'%{keyword}%'))
                result = c.fetchone()
                if result:
                    term, trans, definition = result
                    text = f"📖 **{term}** (探索教育)\n🀄️ {trans}\n📝 {definition}"
                    reply = TextMessage(text=text, quick_reply=get_main_quick_reply())
                else:
                    reply = TextMessage(text=f"❌ 查無「{keyword}」", quick_reply=get_main_quick_reply())
        conn.close()
    
    elif msg_lower.startswith("新增 "):
        task = msg[3:]
        todo_date = datetime.now().strftime('%Y-%m-%d')
        conn = sqlite3.connect('course_bot.db')
        c = conn.cursor()
        
        if is_teacher:
            c.execute("INSERT INTO teacher_todos (task, todo_date, todo_time, created_at) VALUES (?, ?, ?, ?)",
                      (task, todo_date, "23:59", datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            reply_text = f"✅ 已新增老師待辦：{task}"
        else:
            c.execute("INSERT INTO student_todos (user_id, task, todo_date, created_at) VALUES (?, ?, ?, ?)",
                      (user_id, task, todo_date, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            reply_text = f"✅ 已新增個人待辦：{task}"
        
        conn.commit()
        conn.close()
        reply = TextMessage(text=reply_text, quick_reply=get_main_quick_reply())
    
    elif msg_lower in ["待辦", "待辦事項", "todo"]:
        conn = sqlite3.connect('course_bot.db')
        c = conn.cursor()
        
        if is_
