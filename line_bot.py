from flask import Flask, request, abort, render_template_string, redirect, session
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

# ========== 初始化資料庫（強制寫入預設資料）==========
def init_db():
    import os
    db_path = 'course_bot.db'
    
    # 刪除舊資料庫
    if os.path.exists(db_path):
        os.remove(db_path)
        print("✅ 已刪除舊資料庫")
    
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    # 建立所有資料表
    c.execute('''CREATE TABLE vocabulary (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        word TEXT UNIQUE,
        meaning TEXT,
        example TEXT
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
    
    # ========== 寫入預設英文單字 ==========
    default_vocab = [
        ("apple", "蘋果 🍎", "I eat an apple every day."),
        ("book", "書 📚", "This is a good book."),
        ("computer", "電腦 💻", "I use computer to study."),
        ("teacher", "老師 👩‍🏫", "My teacher is very kind."),
        ("student", "學生 🧑‍🎓", "Every student should do homework."),
    ]
    c.executemany("INSERT INTO vocabulary (word, meaning, example) VALUES (?, ?, ?)", default_vocab)
    print("✅ 已寫入英文單字")
    
    # ========== 寫入預設統計名詞 ==========
    default_stats = [
        ("t-test", "t檢定", "比較兩組樣本平均數是否有顯著差異", 
         "from scipy import stats\nimport numpy as np\n\ngroup1 = [85, 88, 90, 92, 86]\ngroup2 = [78, 82, 80, 85, 79]\n\nt_stat, p_value = stats.ttest_ind(group1, group2)\n\nprint(f't值: {t_stat:.4f}')\nprint(f'p值: {p_value:.4f}')", 1),
        ("ANOVA", "變異數分析", "比較三組以上樣本平均數是否有顯著差異", 
         "from scipy import stats\n\ngroup1 = [85, 88, 90, 92, 86]\ngroup2 = [78, 82, 80, 85, 79]\ngroup3 = [75, 78, 76, 80, 77]\n\nf_stat, p_value = stats.f_oneway(group1, group2, group3)", 1),
        ("correlation", "相關分析", "探討兩個連續變數之間的線性關係強度", 
         "from scipy import stats\n\nx = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]\ny = [2, 4, 6, 8, 10, 12, 14, 16, 18, 20]\n\nr, p_value = stats.pearsonr(x, y)", 1),
        ("regression", "迴歸分析", "建立自變數與依變數之間的預測模型", 
         "from sklearn.linear_model import LinearRegression\n\nX = [[1], [2], [3], [4], [5]]\ny = [2, 4, 6, 8, 10]\n\nmodel = LinearRegression()\nmodel.fit(X, y)\npredict = model.predict([[6]])\nprint(f'預測值: {predict[0]:.2f}')", 0),
        ("Chi-square", "卡方檢定", "檢驗兩個類別變數之間是否獨立", 
         "from scipy import stats\n\nobserved = [[10, 20, 30], [6, 9, 17]]\nchi2, p, dof, expected = stats.chi2_contingency(observed)\nprint(f'卡方值: {chi2:.4f}')", 0),
        ("p-value", "p值", "在虛無假設為真下，觀察到當前結果或更極端結果的機率", 
         "if p_value < 0.05:\n    print('統計顯著')\nelse:\n    print('未達統計顯著')", 1),
    ]
    c.executemany("INSERT INTO glossary_stats (term, translation, definition, code, is_starred) VALUES (?, ?, ?, ?, ?)", default_stats)
    print("✅ 已寫入統計名詞")
    
    # ========== 寫入預設社會學名詞 ==========
    default_socio = [
        ("sports socialization", "運動社會化", "個人透過運動參與學習社會規範、價值觀和行為模式的過程", 1),
        ("social stratification", "社會階層化", "社會依據財富、權力、聲望等資源將人群分層的現象，運動參與也受此影響", 1),
        ("gender ideology", "性別意識形態", "社會對男性與女性在運動中應有的角色、行為和價值的期待與刻板印象", 1),
        ("sports fan", "運動迷", "對特定運動隊伍、運動員或運動項目有強烈情感認同和支持的人", 1),
        ("symbolic interactionism", "符號互動論", "透過運動中的符號、語言和互動來理解社會意義的理論視角", 0),
        ("conflict theory", "衝突理論", "檢視運動如何反映和強化社會不平等與權力關係", 1),
        ("functionalist theory", "功能論", "分析運動對社會穩定、整合和秩序維持的貢獻", 0),
        ("commercialization", "商業化", "運動逐漸被市場邏輯主導，追求利潤極大化的現象", 0),
        ("doping", "禁藥使用", "運動員使用禁用物質以提升表現，涉及倫理與健康議題", 1),
        ("sports nationalism", "運動民族主義", "透過國際運動賽事表達和強化國家認同與愛國情懷", 0),
    ]
    c.executemany("INSERT INTO glossary_socio (term, translation, definition, is_starred) VALUES (?, ?, ?, ?)", default_socio)
    print("✅ 已寫入社會學名詞")
    
    # ========== 寫入預設探索教育名詞 ==========
    default_outdoor = [
        ("experiential learning", "體驗式學習", "透過直接經驗和反思來學習的循環過程：具體經驗→反思觀察→抽象概念→主動驗證", 1),
        ("challenge by choice", "自願挑戰", "參與者可依自身意願決定是否參與及參與程度，確保心理安全感", 1),
        ("full value contract", "全價值契約", "團體成員共同建立的參與規範、目標和承諾，確保每個人的價值被尊重", 1),
        ("debriefing", "反思回饋", "活動結束後引導參與者分享經驗、感受和學習的結構化討論過程", 1),
        ("comfort zone", "舒適圈", "個人感到熟悉、安全、無壓力的狀態區域", 0),
        ("stretch zone", "伸展圈", "在支持環境下適度挑戰自我，促進成長的區域", 1),
        ("panic zone", "恐慌圈", "壓力過大導致無法學習和成長的區域", 0),
        ("ropes course", "繩索課程", "利用高低空繩索設施進行的體驗教育活動", 0),
        ("initiative task", "團隊任務", "需要團隊合作解決問題的活動，通常有明確目標和限制條件", 0),
        ("processing", "引導討論", "帶領參與者反思活動經驗，連結到日常生活的引導技巧", 1),
    ]
    c.executemany("INSERT INTO glossary_outdoor (term, translation, definition, is_starred) VALUES (?, ?, ?, ?)", default_outdoor)
    print("✅ 已寫入探索教育名詞")
    
    conn.commit()
    
    # 驗證寫入結果
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

# ========== 天氣函數 ==========
def get_weather_by_coords(lat, lon):
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true&temperature_unit=celsius&timezone=Asia/Taipei"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            temp = data['current_weather']['temperature']
            code = data['current_weather']['weathercode']
            weather_codes = {0: "☀️晴天", 1: "🌤️晴時多雲", 2: "⛅多雲", 3: "☁️陰天", 61: "🌧️下雨", 95: "⛈️雷雨"}
            weather = weather_codes.get(code, "🌡️")
            return f"{weather} {int(temp)}°C"
    except:
        pass
    return "晴天 26°C"

def get_city_from_coords(lat, lon):
    try:
        url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&accept-language=zh-TW"
        r = requests.get(url, headers={'User-Agent': 'LineBot/1.0'}, timeout=5)
        data = r.json()
        city = data.get('address', {}).get('city', '') or data.get('address', {}).get('town', '') or data.get('address', {}).get('county', '')
        return city if city else "您的位置"
    except:
        return "您的位置"

# ========== 6個常駐按鈕選單 ==========
def get_main_quick_reply():
    return QuickReply(
        items=[
            QuickReplyItem(action=MessageAction(label="🌤️天氣", text="天氣")),
            QuickReplyItem(action=MessageAction(label="📚英字", text="單字")),
            QuickReplyItem(action=MessageAction(label="📊統計", text="統計")),
            QuickReplyItem(action=MessageAction(label="⚽社會", text="社會學")),
            QuickReplyItem(action=MessageAction(label="🏕️探索", text="探索")),
            QuickReplyItem(action=MessageAction(label="✅待辦", text="待辦")),
        ]
    )

# ========== 分頁設定 ==========
PAGE_SIZE = 10

# ========== 統計查詢函數 ==========
def get_stats_list(page=1, keyword=None):
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    offset = (page - 1) * PAGE_SIZE
    if keyword:
        c.execute("SELECT id, term, translation FROM glossary_stats WHERE term LIKE ? OR translation LIKE ? ORDER BY id LIMIT ? OFFSET ?", 
                  (f'%{keyword}%', f'%{keyword}%', PAGE_SIZE, offset))
        total = c.execute("SELECT COUNT(*) FROM glossary_stats WHERE term LIKE ? OR translation LIKE ?", 
                          (f'%{keyword}%', f'%{keyword}%')).fetchone()[0]
    else:
        c.execute("SELECT id, term, translation FROM glossary_stats ORDER BY id LIMIT ? OFFSET ?", (PAGE_SIZE, offset))
        total = c.execute("SELECT COUNT(*) FROM glossary_stats").fetchone()[0]
    results = c.fetchall()
    conn.close()
    return results, total

def get_stats_detail(term_id):
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("SELECT term, translation, definition, code FROM glossary_stats WHERE id = ?", (term_id,))
    result = c.fetchone()
    conn.close()
    return result

# ========== 社會學查詢函數 ==========
def get_socio_list(page=1, keyword=None):
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    offset = (page - 1) * PAGE_SIZE
    if keyword:
        c.execute("SELECT id, term, translation FROM glossary_socio WHERE term LIKE ? OR translation LIKE ? ORDER BY id LIMIT ? OFFSET ?", 
                  (f'%{keyword}%', f'%{keyword}%', PAGE_SIZE, offset))
        total = c.execute("SELECT COUNT(*) FROM glossary_socio WHERE term LIKE ? OR translation LIKE ?", 
                          (f'%{keyword}%', f'%{keyword}%')).fetchone()[0]
    else:
        c.execute("SELECT id, term, translation FROM glossary_socio ORDER BY id LIMIT ? OFFSET ?", (PAGE_SIZE, offset))
        total = c.execute("SELECT COUNT(*) FROM glossary_socio").fetchone()[0]
    results = c.fetchall()
    conn.close()
    return results, total

def get_socio_detail(term_id):
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("SELECT term, translation, definition FROM glossary_socio WHERE id = ?", (term_id,))
    result = c.fetchone()
    conn.close()
    return result

# ========== 探索教育查詢函數 ==========
def get_outdoor_list(page=1, keyword=None):
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    offset = (page - 1) * PAGE_SIZE
    if keyword:
        c.execute("SELECT id, term, translation FROM glossary_outdoor WHERE term LIKE ? OR translation LIKE ? ORDER BY id LIMIT ? OFFSET ?", 
                  (f'%{keyword}%', f'%{keyword}%', PAGE_SIZE, offset))
        total = c.execute("SELECT COUNT(*) FROM glossary_outdoor WHERE term LIKE ? OR translation LIKE ?", 
                          (f'%{keyword}%', f'%{keyword}%')).fetchone()[0]
    else:
        c.execute("SELECT id, term, translation FROM glossary_outdoor ORDER BY id LIMIT ? OFFSET ?", (PAGE_SIZE, offset))
        total = c.execute("SELECT COUNT(*) FROM glossary_outdoor").fetchone()[0]
    results = c.fetchall()
    conn.close()
    return results, total

def get_outdoor_detail(term_id):
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("SELECT term, translation, definition FROM glossary_outdoor WHERE id = ?", (term_id,))
    result = c.fetchone()
    conn.close()
    return result

def get_random_vocab():
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("SELECT word, meaning, example FROM vocabulary ORDER BY RANDOM() LIMIT 1")
    result = c.fetchone()
    conn.close()
    return result

# ========== 待辦推播 ==========
def push_todos():
    tz = pytz.timezone('Asia/Taipei')
    now = datetime.now(tz)
    today_str = now.strftime('%Y-%m-%d')
    now_time = now.strftime('%H:%M')
    
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    
    # 1. 老師個人待辦推播
    c.execute("SELECT id, task FROM teacher_todos WHERE todo_date = ? AND todo_time <= ? AND status = 'pending'", (today_str, now_time))
    teacher_todos = c.fetchall()
    if teacher_todos and TEACHER_USER_ID:
        for tid, task in teacher_todos:
            try:
                with ApiClient(configuration) as api_client:
                    line_bot_api = MessagingApi(api_client)
                    line_bot_api.push_message(PushMessageRequest(to=TEACHER_USER_ID, messages=[TextMessage(text=f"👨‍🏫 老師待辦提醒：{task}")]))
                c.execute("UPDATE teacher_todos SET status = 'done' WHERE id = ?", (tid,))
            except Exception as e:
                print(f"老師待辦推播失敗: {e}")
    
    # 2. 全班共同待辦推播
    c.execute("SELECT id, task FROM class_todos WHERE todo_date = ? AND todo_time <= ? AND status = 'pending'", (today_str, now_time))
    class_todos = c.fetchall()
    
    if class_todos:
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
    
    # 3. 學生個人待辦推播（早上7點和晚上9點）
    if now.hour == 7:
        title = "🌅 早安！今天的待辦事項："
        date_str = today_str
    elif now.hour == 21:
        title = "🌙 晚安！明天的待辦事項："
        date_str = (now + timedelta(days=1)).strftime('%Y-%m-%d')
    else:
        conn.commit()
        conn.close()
        return
    
    c.execute("SELECT user_id FROM users")
    users = [row[0] for row in c.fetchall()]
    
    for user_id in users:
        c.execute("SELECT id, task FROM student_todos WHERE user_id = ? AND todo_date = ? AND status = 'pending'", (user_id, date_str))
        todos = c.fetchall()
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
    
    conn.commit()
    conn.close()

# ========== 啟動排程 ==========
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
    
    welcome_text = "🤖 歡迎使用 HANK EduMentor！\n\n📌 點擊下方按鈕使用功能：\n• 🌤️天氣 - 傳送位置查天氣\n• 📚英字 - 隨機英文單字\n• 📊統計 - 統計專有名詞\n• ⚽社會 - 運動社會學\n• 🏕️探索 - 探索教育\n• ✅待辦 - 管理待辦事項"
    
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
    city = get_city_from_coords(lat, lon)
    weather = get_weather_by_coords(lat, lon)
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
    
    # 判斷是否為老師
    is_teacher = (user_id == TEACHER_USER_ID)
    
    # ========== 主選單 ==========
    if msg_lower in ["幫助", "選單", "menu", "help"]:
        reply = TextMessage(text="🤖 請點擊下方按鈕：", quick_reply=get_main_quick_reply())
    
    # ========== 天氣 ==========
    elif msg_lower in ["天氣", "weather"]:
        reply = TextMessage(
            text="📍 如何取得天氣？\n\n1️⃣ 點選左下角「＋」\n2️⃣ 選擇「位置」\n3️⃣ 傳送目前位置",
            quick_reply=get_main_quick_reply()
        )
    
    # ========== 英文單字 ==========
    elif msg_lower in ["單字", "english", "vocab"]:
        result = get_random_vocab()
        if result:
            word, meaning, example = result
            text = f"📖 {word} = {meaning}"
            if example:
                text += f"\n📝 例句：{example}"
            reply = TextMessage(text=text, quick_reply=get_main_quick_reply())
        else:
            reply = TextMessage(text="📖 暫無單字", quick_reply=get_main_quick_reply())
    
    # ========== 統計 ==========
    elif msg_lower in ["統計", "statistics"]:
        session['current_subject'] = 'stats'
        session['stats_page'] = 1
        session['stats_keyword'] = None
        data, total = get_stats_list(1)
        total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
        
        if data:
            text = f"📊 統計專有名詞 (第1頁/共{total_pages}頁)\n\n"
            for i, (sid, term, trans) in enumerate(data, 1):
                text += f"{i}. {term} - {trans}\n"
            text += f"\n💡 輸入數字查詳細（1~{len(data)}），輸入「下一頁」，或輸入「查 關鍵字」搜尋"
            reply = TextMessage(text=text, quick_reply=get_main_quick_reply())
        else:
            reply = TextMessage(text="📊 暫無統計資料", quick_reply=get_main_quick_reply())
    
    # ========== 社會學 ==========
    elif msg_lower in ["社會學", "sociology"]:
        session['current_subject'] = 'socio'
        session['socio_page'] = 1
        session['socio_keyword'] = None
        data, total = get_socio_list(1)
        total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
        
        if data:
            text = f"⚽ 運動社會學 (第1頁/共{total_pages}頁)\n\n"
            for i, (sid, term, trans) in enumerate(data, 1):
                text += f"{i}. {term} - {trans}\n"
            text += f"\n💡 輸入數字查詳細（1~{len(data)}），輸入「下一頁」，或輸入「查 關鍵字」搜尋"
            reply = TextMessage(text=text, quick_reply=get_main_quick_reply())
        else:
            reply = TextMessage(text="⚽ 暫無社會學資料", quick_reply=get_main_quick_reply())
    
    # ========== 探索教育 ==========
    elif msg_lower in ["探索", "outdoor"]:
        session['current_subject'] = 'outdoor'
        session['outdoor_page'] = 1
        session['outdoor_keyword'] = None
        data, total = get_outdoor_list(1)
        total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
        
        if data:
            text = f"🏕️ 探索教育 (第1頁/共{total_pages}頁)\n\n"
            for i, (sid, term, trans) in enumerate(data, 1):
                text += f"{i}. {term} - {trans}\n"
            text += f"\n💡 輸入數字查詳細（1~{len(data)}），輸入「下一頁」，或輸入「查 關鍵字」搜尋"
            reply = TextMessage(text=text, quick_reply=get_main_quick_reply())
        else:
            reply = TextMessage(text="🏕️ 暫無探索教育資料", quick_reply=get_main_quick_reply())
    
    # ========== 分頁處理 ==========
    elif msg_lower in ["下一頁", "上一頁"]:
        current_subject = session.get('current_subject', '')
        
        if current_subject == 'stats':
            page = session.get('stats_page', 1)
            keyword = session.get('stats_keyword', None)
            if msg_lower == "下一頁":
                page += 1
            else:
                page -= 1
            page = max(1, page)
            data, total = get_stats_list(page, keyword)
            total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
            if page > total_pages and total_pages > 0:
                page = total_pages
                data, total = get_stats_list(page, keyword)
            session['stats_page'] = page
            
            if data:
                title = "📊 統計專有名詞"
                if keyword:
                    title += f" (搜尋：{keyword})"
                text = f"{title} (第{page}頁/共{total_pages}頁)\n\n"
                for i, (sid, term, trans) in enumerate(data, 1):
                    text += f"{i}. {term} - {trans}\n"
                text += f"\n💡 輸入數字查詳細"
                reply = TextMessage(text=text, quick_reply=get_main_quick_reply())
            else:
                reply = TextMessage(text="📊 查無資料", quick_reply=get_main_quick_reply())
        
        elif current_subject == 'socio':
            page = session.get('socio_page', 1)
            keyword = session.get('socio_keyword', None)
            if msg_lower == "下一頁":
                page += 1
            else:
                page -= 1
            page = max(1, page)
            data, total = get_socio_list(page, keyword)
            total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
            if page > total_pages and total_pages > 0:
                page = total_pages
                data, total = get_socio_list(page, keyword)
            session['socio_page'] = page
            
            if data:
                title = "⚽ 運動社會學"
                if keyword:
                    title += f" (搜尋：{keyword})"
                text = f"{title} (第{page}頁/共{total_pages}頁)\n\n"
                for i, (sid, term, trans) in enumerate(data, 1):
                    text += f"{i}. {term} - {trans}\n"
                text += f"\n💡 輸入數字查詳細"
                reply = TextMessage(text=text, quick_reply=get_main_quick_reply())
            else:
                reply = TextMessage(text="⚽ 查無資料", quick_reply=get_main_quick_reply())
        
        elif current_subject == 'outdoor':
            page = session.get('outdoor_page', 1)
            keyword = session.get('outdoor_keyword', None)
            if msg_lower == "下一頁":
                page += 1
            else:
                page -= 1
            page = max(1, page)
            data, total = get_outdoor_list(page, keyword)
            total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
            if page > total_pages and total_pages > 0:
                page = total_pages
                data, total = get_outdoor_list(page, keyword)
            session['outdoor_page'] = page
            
            if data:
                title = "🏕️ 探索教育"
                if keyword:
                    title += f" (搜尋：{keyword})"
                text = f"{title} (第{page}頁/共{total_pages}頁)\n\n"
                for i, (sid, term, trans) in enumerate(data, 1):
                    text += f"{i}. {term} - {trans}\n"
                text += f"\n💡 輸入數字查詳細"
                reply = TextMessage(text=text, quick_reply=get_main_quick_reply())
            else:
                reply = TextMessage(text="🏕️ 查無資料", quick_reply=get_main_quick_reply())
        else:
            reply = TextMessage(text="請先選擇一個科目（統計/社會學/探索）", quick_reply=get_main_quick_reply())
    
    # ========== 關鍵字搜尋 ==========
    elif msg_lower.startswith("查 "):
        keyword = msg_lower[3:]
        current_subject = session.get('current_subject', '')
        
        if current_subject == 'stats':
            session['stats_keyword'] = keyword
            session['stats_page'] = 1
            data, total = get_stats_list(1, keyword)
            total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
            
            if data:
                text = f"📊 統計專有名詞 (搜尋：{keyword}) (第1頁/共{total_pages}頁)\n\n"
                for i, (sid, term, trans) in enumerate(data, 1):
                    text += f"{i}. {term} - {trans}\n"
                text += f"\n💡 輸入數字查詳細，輸入「下一頁」看更多"
                reply = TextMessage(text=text, quick_reply=get_main_quick_reply())
            else:
                reply = TextMessage(text=f"❌ 查無「{keyword}」", quick_reply=get_main_quick_reply())
        
        elif current_subject == 'socio':
            session['socio_keyword'] = keyword
            session['socio_page'] = 1
            data, total = get_socio_list(1, keyword)
            total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
            
            if data:
                text = f"⚽ 運動社會學 (搜尋：{keyword}) (第1頁/共{total_pages}頁)\n\n"
                for i, (sid, term, trans) in enumerate(data, 1):
                    text += f"{i}. {term} - {trans}\n"
                text += f"\n💡 輸入數字查詳細"
                reply = TextMessage(text=text, quick_reply=get_main_quick_reply())
            else:
                reply = TextMessage(text=f"❌ 查無「{keyword}」", quick_reply=get_main_quick_reply())
        
        elif current_subject == 'outdoor':
            session['outdoor_keyword'] = keyword
            session['outdoor_page'] = 1
            data, total = get_outdoor_list(1, keyword)
            total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
            
            if data:
                text = f"🏕️ 探索教育 (搜尋：{keyword}) (第1頁/共{total_pages}頁)\n\n"
                for i, (sid, term, trans) in enumerate(data, 1):
                    text += f"{i}. {term} - {trans}\n"
                text += f"\n💡 輸入數字查詳細"
                reply = TextMessage(text=text, quick_reply=get_main_quick_reply())
            else:
                reply = TextMessage(text=f"❌ 查無「{keyword}」", quick_reply=get_main_quick_reply())
        else:
            # 跨科目搜尋（先從統計找）
            data, total = get_stats_list(1, keyword)
            if data:
                text = f"📊 統計專有名詞 (搜尋：{keyword})\n\n"
                for i, (sid, term, trans) in enumerate(data[:5], 1):
                    text += f"{i}. {term} - {trans}\n"
                text += f"\n💡 輸入「統計」後再輸入數字查詳細"
                reply = TextMessage(text=text, quick_reply=get_main_quick_reply())
            else:
                reply = TextMessage(text=f"❌ 查無「{keyword}」\n\n試試：t-test, ANOVA, 運動社會化, 體驗式學習", quick_reply=get_main_quick_reply())
    
    # ========== 數字查詢 ==========
    elif msg_lower.isdigit():
        num = int(msg_lower)
        current_subject = session.get('current_subject', '')
        
        if current_subject == 'stats':
            page = session.get('stats_page', 1)
            keyword = session.get('stats_keyword', None)
            data, total = get_stats_list(page, keyword)
            if 1 <= num <= len(data):
                detail = get_stats_detail(data[num-1][0])
                if detail:
                    term, trans, definition, code = detail
                    text = f"📖 **{term}**\n🀄️ {trans}\n📝 {definition}"
                    if code:
                        text += f"\n\n💻 程式碼：\n```\n{code}\n```"
                    reply = TextMessage(text=text, quick_reply=get_main_quick_reply())
                else:
                    reply = TextMessage(text="查無資料", quick_reply=get_main_quick_reply())
            else:
                reply = TextMessage(text=f"請輸入 1-{len(data)} 之間的數字", quick_reply=get_main_quick_reply())
        
        elif current_subject == 'socio':
            page = session.get('socio_page', 1)
            keyword = session.get('socio_keyword', None)
            data, total = get_socio_list(page, keyword)
            if 1 <= num <= len(data):
                detail = get_socio_detail(data[num-1][0])
                if detail:
                    term, trans, definition = detail
                    text = f"📖 **{term}**\n🀄️ {trans}\n📝 {definition}"
                    reply = TextMessage(text=text, quick_reply=get_main_quick_reply())
                else:
                    reply = TextMessage(text="查無資料", quick_reply=get_main_quick_reply())
            else:
                reply = TextMessage(text=f"請輸入 1-{len(data)} 之間的數字", quick_reply=get_main_quick_reply())
        
        elif current_subject == 'outdoor':
            page = session.get('outdoor_page', 1)
            keyword = session.get('outdoor_keyword', None)
            data, total = get_outdoor_list(page, keyword)
            if 1 <= num <= len(data):
                detail = get_outdoor_detail(data[num-1][0])
                if detail:
                    term, trans, definition = detail
                    text = f"📖 **{term}**\n🀄️ {trans}\n📝 {definition}"
                    reply = TextMessage(text=text, quick_reply=get_main_quick_reply())
                else:
                    reply = TextMessage(text="查無資料", quick_reply=get_main_quick_reply())
            else:
                reply = TextMessage(text=f"請輸入 1-{len(data)} 之間的數字", quick_reply=get_main_quick_reply())
        
        else:
            reply = TextMessage(text="請先選擇一個科目（統計/社會學/探索）", quick_reply=get_main_quick_reply())
    
    # ========== 待辦事項 ==========
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
    
    # ========== 取得我的 User ID ==========
    elif msg_lower == "取得我的id":
        reply = TextMessage(text=f"🔑 你的 LINE User ID 是：\n{user_id}\n\n請將此 ID 設定到 Render 環境變數 TEACHER_USER_ID", quick_reply=get_main_quick_reply())
    
    else:
        reply = TextMessage(
            text=f"你說了：「{msg}」\n\n📌 點擊下方按鈕使用功能：\n\n或輸入：\n• 統計 - 統計名詞\n• 社會學 - 社會學名詞\n• 探索 - 探索教育\n• 查 t-test - 搜尋\n• 新增 買牛奶 - 待辦",
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
        'vocabulary': {'table': 'vocabulary', 'name': '英文單字', 'columns': ['word', 'meaning', 'example'], 'labels': ['單字', '意思', '例句']},
        'stats': {'table': 'glossary_stats', 'name': '統計專有名詞', 'columns': ['term', 'translation', 'definition', 'code', 'is_starred'], 'labels': ['英文/名詞', '中文翻譯', '解釋', '程式碼', '核心']},
        'socio': {'table': 'glossary_socio', 'name': '運動社會學', 'columns': ['term', 'translation', 'definition', 'is_starred'], 'labels': ['英文/名詞', '中文翻譯', '解釋', '核心']},
        'outdoor': {'table': 'glossary_outdoor', 'name': '探索教育', 'columns': ['term', 'translation', 'definition', 'is_starred'], 'labels': ['英文/名詞', '中文翻譯', '解釋', '核心']},
        'teacher_todo': {'table': 'teacher_todos', 'name': '老師個人待辦', 'columns': ['task', 'todo_date', 'todo_time'], 'labels': ['待辦事項', '日期(YYYY-MM-DD)', '時間(HH:MM)']},
        'class_todo': {'table': 'class_todos', 'name': '全班共同待辦', 'columns': ['task', 'todo_date', 'todo_time'], 'labels': ['待辦事項', '日期(YYYY-MM-DD)', '時間(HH:MM)']},
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
        {% for row in rows %}
        <td>
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
    </table>
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
    
    <table border="1" cellpadding="8" style="border-collapse: collapse; width: 100%;">
        <tr><th>ID</th><th>學生ID</th><th>待辦事項</th><th>日期</th><th>狀態</th><th>操作</th></tr>
        {% for row in rows %}
        <tr>
            <td>{{ row[0] }}</td>
            <td>{{ row[1][:20] }}...{% if row[1]|length > 20 %}{% endif %}</td>
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
