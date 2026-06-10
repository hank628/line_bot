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
last_push_record = {}

# ========== 初始化資料庫（安全版本 - 不會自動刪除資料）==========
def init_db():
    import os
    db_path = 'course_bot.db'
    
    # 檢查資料庫是否已存在且有效
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            # 檢查必要的資料表是否存在且有資料
            c.execute("SELECT COUNT(*) FROM glossary_stats")
            stats_count = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM glossary_socio")
            socio_count = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM glossary_outdoor")
            outdoor_count = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM vocabulary")
            vocab_count = c.fetchone()[0]
            conn.close()
            
            print(f"✅ 資料庫已存在 - 統計:{stats_count} 社會學:{socio_count} 探索:{outdoor_count} 單字:{vocab_count}")
            
            # 如果所有資料表都有資料，直接返回，不重建
            if stats_count > 0 and socio_count > 0 and outdoor_count > 0 and vocab_count > 0:
                print("✅ 資料庫完整，跳過初始化")
                return
        except Exception as e:
            print(f"資料庫檢查錯誤: {e}")
            # 資料庫可能損壞，需要重建
    
    # 備份舊資料庫（如果存在）
    if os.path.exists(db_path):
        backup_path = f"{db_path}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        os.rename(db_path, backup_path)
        print(f"⚠️ 已備份舊資料庫至: {backup_path}")
    
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    # 建立所有資料表
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
    print("✅ 已寫入預設英文單字")
    
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
    print("✅ 已寫入預設統計名詞")
    
    # 預設社會學名詞
    default_socio = [
        ("sports socialization", "運動社會化", "個人透過運動參與學習社會規範、價值觀和行為模式的過程", 1),
        ("social stratification", "社會階層化", "社會依據財富、權力、聲望等資源將人群分層的現象", 1),
        ("gender ideology", "性別意識形態", "社會對男性與女性在運動中應有的角色、行為和價值的期待", 1),
        ("sports fan", "運動迷", "對特定運動隊伍、運動員或運動項目有強烈情感認同和支持的人", 1),
    ]
    c.executemany("INSERT INTO glossary_socio (term, translation, definition, is_starred) VALUES (?, ?, ?, ?)", default_socio)
    print("✅ 已寫入預設社會學名詞")
    
    # 預設探索教育名詞
    default_outdoor = [
        ("experiential learning", "體驗式學習", "透過直接經驗和反思來學習的循環過程", 1),
        ("challenge by choice", "自願挑戰", "參與者可依自身意願決定是否參與及參與程度", 1),
        ("debriefing", "反思回饋", "活動結束後引導參與者分享經驗、感受和學習的結構化討論過程", 1),
    ]
    c.executemany("INSERT INTO glossary_outdoor (term, translation, definition, is_starred) VALUES (?, ?, ?, ?)", default_outdoor)
    print("✅ 已寫入預設探索教育名詞")
    
    conn.commit()
    
    # 驗證
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
    
    # 1. 老師個人待辦推播
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
    
    # ========== 統計列表 ==========
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
    
    # ========== 社會學列表 ==========
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
    
    # ========== 探索教育列表 ==========
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
        
        if is_teacher:
            c.execute("SELECT id, task, todo_date FROM teacher_todos WHERE status = 'pending' ORDER BY todo_date")
            todos = c.fetchall()
            if todos:
                text = "👨‍🏫 老師待辦清單：\n"
                for tid, task, date_str in todos:
                    text += f"{tid}. [{date_str}] {task}\n"
                text += "\n💡 完成請輸入「完成 編號」"
            else:
                text = "📋 沒有老師待辦事項\n\n💡 輸入「新增 買牛奶」新增"
        else:
            c.execute("SELECT id, task, todo_date FROM student_todos WHERE user_id = ? AND status = 'pending' ORDER BY todo_date", (user_id,))
            todos = c.fetchall()
            if todos:
                text = "✅ 個人待辦清單：\n"
                for tid, task, date_str in todos:
                    text += f"{tid}. [{date_str}] {task}\n"
                text += "\n💡 完成請輸入「完成 編號」"
            else:
                text = "📋 沒有個人待辦事項\n\n💡 輸入「新增 買牛奶」新增"
        
        conn.close()
        reply = TextMessage(text=text, quick_reply=get_main_quick_reply())
    
    elif msg_lower.startswith("完成 "):
        try:
            todo_id = int(msg_lower[3:])
            conn = sqlite3.connect('course_bot.db')
            c = conn.cursor()
            
            if is_teacher:
                c.execute("UPDATE teacher_todos SET status = 'done' WHERE id = ?", (todo_id,))
            else:
                c.execute("UPDATE student_todos SET status = 'done' WHERE id = ? AND user_id = ?", (todo_id, user_id))
            
            conn.commit()
            conn.close()
            reply = TextMessage(text=f"✅ 已完成編號 {todo_id}", quick_reply=get_main_quick_reply())
        except:
            reply = TextMessage(text="請輸入：完成 1", quick_reply=get_main_quick_reply())
    
    elif "取得我的id" in msg_lower or "取得id" in msg_lower:
        reply = TextMessage(text=f"🔑 你的 LINE User ID 是：\n{user_id}", quick_reply=get_main_quick_reply())
    
    else:
        reply = TextMessage(
            text=f"你說了：「{msg}」\n\n📌 點擊下方按鈕：\n• 統計 - 查看統計名詞\n• 社會學 - 查看社會學名詞\n• 探索 - 查看探索教育名詞\n• 新增 買牛奶 - 待辦\n\n📝 快捷查詢：\n• se3 - 查統計 ID=3\n• 統計頁2 - 跳到第2頁",
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

def get_table_info(table_type):
    tables = {
        'vocabulary': {'table': 'vocabulary', 'name': '英文單字', 'columns': ['word', 'meaning'], 'labels': ['單字', '意思']},
        'stats': {'table': 'glossary_stats', 'name': '統計專有名詞', 'columns': ['term', 'translation', 'definition', 'code'], 'labels': ['英文/名詞', '中文翻譯', '解釋', '程式碼']},
        'socio': {'table': 'glossary_socio', 'name': '運動社會學', 'columns': ['term', 'translation', 'definition'], 'labels': ['英文/名詞', '中文翻譯', '解釋']},
        'outdoor': {'table': 'glossary_outdoor', 'name': '探索教育', 'columns': ['term', 'translation', 'definition'], 'labels': ['英文/名詞', '中文翻譯', '解釋']},
        'teacher_todo': {'table': 'teacher_todos', 'name': '老師個人待辦', 'columns': ['task', 'todo_date', 'todo_time'], 'labels': ['待辦事項', '日期(YYYY-MM-DD)', '時間(HH:MM)']},
        'class_todo': {'table': 'class_todos', 'name': '全班共同待辦', 'columns': ['task', 'todo_date', 'todo_time'], 'labels': ['待辦事項', '日期(YYYY-MM-DD)', '時間(HH:MM)']},
        'student_todo': {'table': 'student_todos', 'name': '學生個人待辦', 'columns': ['user_id', 'task', 'todo_date', 'status'], 'labels': ['使用者ID', '待辦事項', '日期', '狀態']},
    }
    return tables.get(table_type)

# CSV 匯出功能
@app.route('/admin/export_csv/<table_type>')
@login_required
def admin_export_csv(table_type):
    info = get_table_info(table_type)
    if not info:
        return redirect('/admin')
    
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute(f"SELECT * FROM {info['table']}")
    rows = c.fetchall()
    conn.close()
    
    column_names = ['id'] + info['labels']
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(column_names)
    
    for row in rows:
        writer.writerow(row)
    
    date_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"{info['name']}_{date_str}.csv"
    
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )

@app.route('/admin/<table_type>')
@login_required
def admin_table(table_type):
    info = get_table_info(table_type)
    if not info:
        return redirect('/admin')
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute(f"SELECT * FROM {info['table']} ORDER BY id")
    rows = c.fetchall()
    conn.close()
    return render_template_string(TABLE_TEMPLATE, rows=rows, info=info, table_type=table_type)

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
    
    content = file.read().decode('utf-8-sig')
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    columns = info['columns']
    
    reader = csv.reader(io.StringIO(content))
    headers = next(reader, None)
    
    for row in reader:
        if len(row) >= len(columns):
            values = row[:len(columns)]
            placeholders = ','.join(['?' for _ in values])
            try:
                c.execute(f"INSERT INTO {info['table']} ({','.join(columns)}) VALUES ({placeholders})", values)
            except Exception as e:
                print(f"匯入錯誤: {e}")
    
    conn.commit()
    conn.close()
    
    return redirect(f'/admin/{table_type}')

@app.route('/admin/student_todos')
@login_required
def admin_student_todos():
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("SELECT id, user_id, task, todo_date, status FROM student_todos ORDER BY todo_date DESC LIMIT 100")
    rows = c.fetchall()
    conn.close()
    return render_template_string(STUDENT_TODOS_TEMPLATE, rows=rows)

@app.route('/admin/delete_student_todo/<int:id>')
@login_required
def admin_delete_student_todo(id):
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("DELETE FROM student_todos WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return redirect('/admin/student_todos')

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
            <h2 style="color: #3498db;">📚 教材管理</h2>
            <a href="/admin/vocabulary" style="display: block; padding: 15px; background: #3498db; color: white; text-decoration: none; border-radius: 8px;">📖 英文單字管理</a>
            <a href="/admin/stats" style="display: block; padding: 15px; background: #2ecc71; color: white; text-decoration: none; border-radius: 8px;">📊 統計專有名詞</a>
            <a href="/admin/socio" style="display: block; padding: 15px; background: #e74c3c; color: white; text-decoration: none; border-radius: 8px;">⚽ 運動社會學</a>
            <a href="/admin/outdoor" style="display: block; padding: 15px; background: #f39c12; color: white; text-decoration: none; border-radius: 8px;">🏕️ 探索教育</a>
            
            <h2 style="color: #9b59b6; margin-top: 20px;">✅ 待辦管理</h2>
            <a href="/admin/teacher_todo" style="display: block; padding: 15px; background: #1abc9c; color: white; text-decoration: none; border-radius: 8px;">👨‍🏫 老師個人待辦</a>
            <a href="/admin/class_todo" style="display: block; padding: 15px; background: #e67e22; color: white; text-decoration: none; border-radius: 8px;">📢 全班共同待辦</a>
            <a href="/admin/student_todos" style="display: block; padding: 15px; background: #95a5a6; color: white; text-decoration: none; border-radius: 8px;">👥 學生個人待辦（僅查看）</a>
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
        <h3>📤 匯出 CSV</h3>
        <a href="/admin/export_csv/{{ table_type }}" style="display: inline-block; padding: 8px 16px; background: #27ae60; color: white; text-decoration: none; border-radius: 5px;">📥 匯出 CSV</a>
    </div>
    
    <div style="margin: 20px 0; padding: 15px; background: #e8f5e9;">
        <h3>📤 匯入 CSV</h3>
        <form method="post" action="/admin/import_csv/{{ table_type }}" enctype="multipart/form-data">
            <input type="file" name="csv_file" accept=".csv" required>
            <button type="submit">匯入</button>
        </form>
        <p style="font-size: 12px;">格式：{{ ', '.join(info.labels) }}</p>
        <p style="font-size: 12px; color: #666;">※ CSV 第一行會自動跳過（視為標題列）</p>
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
        {% for row in rows %}
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
        </tr>
        {% endfor %}
    <table>
</body>
</html>
'''

STUDENT_TODOS_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head><title>學生待辦事項</title><meta charset="UTF-8"></head>
<body style="font-family: Arial; padding: 20px;">
    <h1>👥 學生個人待辦事項</h1>
    <p><a href="/admin">← 返回首頁</a> | <a href="/logout">登出</a></p>
    <p>⚠️ 此為學生自行新增的待辦，老師僅可查看，無法修改狀態。</p>
    
    <div style="margin: 20px 0; padding: 15px; background: #e8f5e9;">
        <h3>📤 匯出 CSV</h3>
        <a href="/admin/export_csv/student_todo" style="display: inline-block; padding: 8px 16px; background: #27ae60; color: white; text-decoration: none; border-radius: 5px;">📥 匯出 CSV</a>
    </div>
    
    <table border="1" cellpadding="8" style="border-collapse: collapse; width: 100%;">
        <tr><th>ID</th><th>學生ID</th><th>待辦事項</th><th>日期</th><th>狀態</th><th>操作</th></tr>
        {% for row in rows %}
        <tr>
            <td>{{ row[0] }}</td>
            <td>{{ row[1][:30] }}...{% if row[1]|length > 30 %}{% endif %}</td>
            <td>{{ row[2] }}</td>
            <td>{{ row[3] }}</td>
            <td>{% if row[4] == 'pending' %}⏳ 待完成{% else %}✅ 已完成{% endif %}</td>
            <td><a href="/admin/delete_student_todo/{{ row[0] }}" onclick="return confirm('確定刪除？')">刪除</a></td>
        </tr>
        {% endfor %}
    </table>
</body>
</html>
'''

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
