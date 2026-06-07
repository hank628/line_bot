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
    
    # 實驗設計與統計 - 專有名詞表
    c.execute('''CREATE TABLE IF NOT EXISTS statistics_glossary (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        term TEXT UNIQUE,
        translation TEXT,
        definition TEXT,
        code TEXT
    )''')
    
    # 運動社會學 - 專有名詞表
    c.execute('''CREATE TABLE IF NOT EXISTS sociology_glossary (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        term TEXT UNIQUE,
        translation TEXT,
        definition TEXT
    )''')
    
    # 探索教育 - 專有名詞表
    c.execute('''CREATE TABLE IF NOT EXISTS outdoor_glossary (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        term TEXT UNIQUE,
        translation TEXT,
        definition TEXT
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
    
    # ========== 預設資料 ==========
    
    # 預設英文單字
    c.execute("SELECT COUNT(*) FROM vocabulary")
    if c.fetchone()[0] == 0:
        default_vocab = [
            ("apple", "蘋果 🍎", "I eat an apple every day."),
            ("book", "書 📚", "This is a good book."),
            ("statistics", "統計學 📊", "Statistics is important for research."),
            ("sociology", "社會學 👥", "Sociology studies human society."),
            ("outdoor", "戶外探索 🏕️", "Outdoor education is fun."),
            ("t-test", "t檢定", "Statistical test for comparing two groups"),
            ("ANOVA", "變異數分析", "Analysis of Variance for comparing multiple groups"),
        ]
        c.executemany("INSERT INTO vocabulary (word, meaning, example) VALUES (?, ?, ?)", default_vocab)
    
    # 預設統計專有名詞
    c.execute("SELECT COUNT(*) FROM statistics_glossary")
    if c.fetchone()[0] == 0:
        default_stats = [
            ("t-test", "t檢定", "比較兩組樣本平均數是否有顯著差異的統計方法", 
             "from scipy import stats\nt_stat, p_value = stats.ttest_ind(group1, group2)"),
            ("ANOVA", "變異數分析", "比較三組以上樣本平均數是否有顯著差異", 
             "from scipy import stats\nf_stat, p_value = stats.f_oneway(group1, group2, group3)"),
            ("correlation", "相關分析", "探討兩個連續變數之間的線性關係強度", 
             "from scipy import stats\nr, p_value = stats.pearsonr(x, y)"),
            ("regression", "迴歸分析", "建立自變數與依變數之間的預測模型", 
             "from sklearn.linear_model import LinearRegression\nmodel = LinearRegression()\nmodel.fit(X, y)"),
            ("Chi-square", "卡方檢定", "檢驗兩個類別變數之間是否獨立", 
             "from scipy import stats\nchi2, p_value, dof, expected = stats.chi2_contingency(contingency_table)"),
            ("p-value", "p值", "在虛無假設為真下，觀察到當前結果或更極端結果的機率", 
             "if p_value < 0.05:\n    print('統計顯著')"),
        ]
        c.executemany("INSERT INTO statistics_glossary (term, translation, definition, code) VALUES (?, ?, ?, ?)", default_stats)
    
    # 預設運動社會學專有名詞
    c.execute("SELECT COUNT(*) FROM sociology_glossary")
    if c.fetchone()[0] == 0:
        default_socio = [
            ("sports socialization", "運動社會化", "個人透過運動參與學習社會規範、價值觀和行為模式的過程"),
            ("social stratification", "社會階層化", "社會依據財富、權力、聲望等資源將人群分層的現象，運動參與也受此影響"),
            ("gender ideology", "性別意識形態", "社會對男性與女性在運動中應有的角色、行為和價值的期待與刻板印象"),
            ("sports fan", "運動迷", "對特定運動隊伍、運動員或運動項目有強烈情感認同和支持的人"),
            ("symbolic interactionism", "符號互動論", "透過運動中的符號、語言和互動來理解社會意義的理論視角"),
            ("conflict theory", "衝突理論", "檢視運動如何反映和強化社會不平等與權力關係"),
            ("functionalist theory", "功能論", "分析運動對社會穩定、整合和秩序維持的貢獻"),
            ("sports nationalism", "運動民族主義", "透過國際運動賽事表達和強化國家認同與愛國情懷"),
            ("commercialization", "商業化", "運動逐漸被市場邏輯主導，追求利潤極大化的現象"),
            ("doping", "禁藥使用", "運動員使用禁用物質以提升表現，涉及倫理與健康議題"),
        ]
        c.executemany("INSERT INTO sociology_glossary (term, translation, definition) VALUES (?, ?, ?)", default_socio)
    
    # 預設探索教育專有名詞
    c.execute("SELECT COUNT(*) FROM outdoor_glossary")
    if c.fetchone()[0] == 0:
        default_outdoor = [
            ("experiential learning", "體驗式學習", "透過直接經驗和反思來學習的循環過程：具體經驗→反思觀察→抽象概念→主動驗證"),
            ("challenge by choice", "自願挑戰", "參與者可依自身意願決定是否參與及參與程度，確保心理安全感"),
            ("full value contract", "全價值契約", "團體成員共同建立的參與規範、目標和承諾，確保每個人的價值被尊重"),
            ("debriefing", "反思回饋", "活動結束後引導參與者分享經驗、感受和學習的結構化討論過程"),
            ("comfort zone", "舒適圈", "個人感到熟悉、安全、無壓力的狀態區域"),
            ("stretch zone", "伸展圈", "在支持環境下適度挑戰自我，促進成長的區域"),
            ("panic zone", "恐慌圈", "壓力過大導致無法學習和成長的區域"),
            ("ropes course", "繩索課程", "利用高低空繩索設施進行的體驗教育活動"),
            ("initiative task", "團隊任務", "需要團隊合作解決問題的活動，通常有明確目標和限制條件"),
            ("processing", "引導討論", "帶領參與者反思活動經驗，連結到日常生活的引導技巧"),
            ("ISOTREK", "戶外探索訓練", "國際戶外探索訓練系統，強調冒險教育和體驗學習"),
            ("Leave No Trace", "無痕山林", "戶外活動中最小化環境衝擊的七項原則"),
        ]
        c.executemany("INSERT INTO outdoor_glossary (term, translation, definition) VALUES (?, ?, ?)", default_outdoor)
    
    conn.commit()
    conn.close()

init_db()

# ========== 按鈕選單 ==========
def get_quick_reply():
    return QuickReply(
        items=[
            QuickReplyItem(action=MessageAction(label="🌤️天氣", text="天氣")),
            QuickReplyItem(action=MessageAction(label="📚英字", text="單字")),
            QuickReplyItem(action=MessageAction(label="📊統計", text="統計")),
            QuickReplyItem(action=MessageAction(label="⚽社會", text="運動社會學")),
            QuickReplyItem(action=MessageAction(label="🏕️探索", text="探索教育")),
            QuickReplyItem(action=MessageAction(label="✅待辦", text="待辦")),
        ]
    )

# ========== 天氣函數 ==========
def get_weather(lat, lon):
    try:
        url = f"https://wttr.in/{lat},{lon}?format=%C+%t&lang=zh"
        response = requests.get(url, timeout=8)
        if response.status_code == 200 and response.text.strip():
            weather_text = response.text.strip()
            parts = weather_text.split()
            if len(parts) >= 2:
                return f"{parts[0]}，{parts[1]}"
    except:
        pass
    
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true&temperature_unit=celsius&timezone=Asia/Taipei"
        response = requests.get(url, timeout=8)
        if response.status_code == 200:
            data = response.json()
            temp = data['current_weather']['temperature']
            code = data['current_weather']['weathercode']
            weather_codes = {0: "☀️晴天", 1: "🌤️晴時多雲", 2: "⛅多雲", 3: "☁️陰天", 61: "🌧️下雨", 95: "⛈️雷雨"}
            weather = weather_codes.get(code, "🌡️")
            return f"{weather}，{temp}°C"
    except:
        pass
    
    conditions = ["☀️晴天", "⛅多雲時晴", "🌤️晴時多雲", "☁️陰天"]
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

# ========== 查詢函數 ==========
def search_statistics(keyword=None):
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    if keyword:
        c.execute("SELECT term, translation, definition, code FROM statistics_glossary WHERE term LIKE ? OR translation LIKE ?", 
                  (f'%{keyword}%', f'%{keyword}%'))
    else:
        c.execute("SELECT term, translation, definition, code FROM statistics_glossary ORDER BY id")
    results = c.fetchall()
    conn.close()
    return results

def search_sociology(keyword=None):
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    if keyword:
        c.execute("SELECT term, translation, definition FROM sociology_glossary WHERE term LIKE ? OR translation LIKE ?", 
                  (f'%{keyword}%', f'%{keyword}%'))
    else:
        c.execute("SELECT term, translation, definition FROM sociology_glossary ORDER BY id")
    results = c.fetchall()
    conn.close()
    return results

def search_outdoor(keyword=None):
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    if keyword:
        c.execute("SELECT term, translation, definition FROM outdoor_glossary WHERE term LIKE ? OR translation LIKE ?", 
                  (f'%{keyword}%', f'%{keyword}%'))
    else:
        c.execute("SELECT term, translation, definition FROM outdoor_glossary ORDER BY id")
    results = c.fetchall()
    conn.close()
    return results

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
    
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text="🤖 歡迎使用 HANK EduMentor！\n\n請選擇功能：", quick_reply=get_quick_reply())]
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
                messages=[TextMessage(text=f"📍 {city}\n🌡️ {weather}", quick_reply=get_quick_reply())]
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
    
    # 主選單
    if msg_lower in ["幫助", "選單", "menu"]:
        reply = TextMessage(text="🤖 HANK EduMentor\n\n請選擇功能：", quick_reply=get_quick_reply())
    
    # 天氣
    elif msg_lower in ["天氣", "weather"]:
        reply = TextMessage(
            text="📍 如何取得天氣？\n\n1️⃣ 點選左下角「＋」\n2️⃣ 選擇「位置」\n3️⃣ 傳送目前位置",
            quick_reply=get_quick_reply()
        )
    
    # 實驗設計與統計
    elif msg_lower in ["統計", "實驗設計與統計", "statistics"]:
        results = search_statistics()
        if results:
            text = "📊 實驗設計與統計\n\n"
            for term, trans, definition, code in results[:10]:
                text += f"• **{term}** - {trans}\n"
            text += "\n💡 輸入「查 [名詞]」看詳細解釋和程式碼"
            reply = TextMessage(text=text, quick_reply=get_quick_reply())
        else:
            reply = TextMessage(text="📊 實驗設計與統計\n\n暫無資料", quick_reply=get_quick_reply())
    
    # 運動社會學
    elif msg_lower in ["運動社會學", "社會學", "sociology"]:
        results = search_sociology()
        if results:
            text = "⚽ 運動社會學\n\n"
            for term, trans, definition in results[:10]:
                text += f"• **{term}** - {trans}\n"
            text += "\n💡 輸入「查 [名詞]」看詳細解釋"
            reply = TextMessage(text=text, quick_reply=get_quick_reply())
        else:
            reply = TextMessage(text="⚽ 運動社會學\n\n暫無資料", quick_reply=get_quick_reply())
    
    # 探索教育
    elif msg_lower in ["探索教育", "探索", "outdoor"]:
        results = search_outdoor()
        if results:
            text = "🏕️ 探索教育\n\n"
            for term, trans, definition in results[:10]:
                text += f"• **{term}** - {trans}\n"
            text += "\n💡 輸入「查 [名詞]」看詳細解釋"
            reply = TextMessage(text=text, quick_reply=get_quick_reply())
        else:
            reply = TextMessage(text="🏕️ 探索教育\n\n暫無資料", quick_reply=get_quick_reply())
    
    # 查詢專有名詞
    elif msg_lower.startswith("查 "):
        keyword = msg_lower[3:]
        found = False
        
        # 查統計
        results = search_statistics(keyword)
        if results:
            term, trans, definition, code = results[0]
            text = f"📖 **{term}**\n🀄️ {trans}\n📝 {definition}"
            if code:
                text += f"\n\n💻 程式碼：\n```python\n{code}\n```"
            reply = TextMessage(text=text, quick_reply=get_quick_reply())
            found = True
        
        # 查社會學
        if not found:
            results = search_sociology(keyword)
            if results:
                term, trans, definition = results[0]
                text = f"📖 **{term}**\n🀄️ {trans}\n📝 {definition}"
                reply = TextMessage(text=text, quick_reply=get_quick_reply())
                found = True
        
        # 查探索教育
        if not found:
            results = search_outdoor(keyword)
            if results:
                term, trans, definition = results[0]
                text = f"📖 **{term}**\n🀄️ {trans}\n📝 {definition}"
                reply = TextMessage(text=text, quick_reply=get_quick_reply())
                found = True
        
        if not found:
            reply = TextMessage(text=f"❌ 查無「{keyword}」\n\n試試：t-test, ANOVA, 運動社會化, 體驗式學習", quick_reply=get_quick_reply())
    
    # 英文單字
    elif msg_lower == "單字":
        conn = sqlite3.connect('course_bot.db')
        c = conn.cursor()
        c.execute("SELECT word, meaning FROM vocabulary ORDER BY RANDOM() LIMIT 1")
        result = c.fetchone()
        conn.close()
        if result:
            reply = TextMessage(text=f"📖 今日單字\n{result[0]} = {result[1]}", quick_reply=get_quick_reply())
        else:
            reply = TextMessage(text="📖 暫無單字", quick_reply=get_quick_reply())
    
    # 待辦事項
    elif msg_lower.startswith("新增 "):
        task = msg[3:]
        todo_date = datetime.now().strftime('%Y-%m-%d')
        conn = sqlite3.connect('course_bot.db')
        c = conn.cursor()
        c.execute("INSERT INTO todos (user_id, task, todo_date, created_at) VALUES (?, ?, ?, ?)",
                  (user_id, task, todo_date, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()
        conn.close()
        reply = TextMessage(text=f"✅ 已新增：{task}", quick_reply=get_quick_reply())
    
    elif msg_lower in ["待辦", "待辦事項", "todo"]:
        conn = sqlite3.connect('course_bot.db')
        c = conn.cursor()
        c.execute("SELECT id, task, todo_date FROM todos WHERE user_id = ? AND status = 'pending' ORDER BY todo_date", (user_id,))
        todos = c.fetchall()
        conn.close()
        if todos:
            text = "✅ 待辦清單：\n"
            for tid, task, date_str in todos:
                text += f"{tid}. [{date_str}] {task}\n"
            text += "\n💡 完成請輸入「完成 編號」"
        else:
            text = "📋 沒有待辦事項\n\n💡 輸入「新增 買牛奶」新增"
        reply = TextMessage(text=text, quick_reply=get_quick_reply())
    
    elif msg_lower.startswith("完成 "):
        try:
            todo_id = int(msg_lower[3:])
            conn = sqlite3.connect('course_bot.db')
            c = conn.cursor()
            c.execute("UPDATE todos SET status = 'done' WHERE id = ? AND user_id = ?", (todo_id, user_id))
            conn.commit()
            conn.close()
            reply = TextMessage(text=f"✅ 已完成編號 {todo_id}", quick_reply=get_quick_reply())
        except:
            reply = TextMessage(text="請輸入：完成 1", quick_reply=get_quick_reply())
    
    else:
        reply = TextMessage(
            text=f"你說了：「{msg}」\n\n📌 試試看：\n• 幫助 - 顯示選單\n• 天氣 - 傳送位置\n• 統計 - 統計名詞\n• 運動社會學\n• 探索教育\n• 查 t-test\n• 新增 買牛奶",
            quick_reply=get_quick_reply()
        )
    
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(reply_token=event.reply_token, messages=[reply])
        )

# ========== HANK EduMentor 管理後台 ==========
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

# ========== 英文單字管理 ==========
@app.route('/admin/vocabulary')
@login_required
def admin_vocabulary():
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("SELECT id, word, meaning, example FROM vocabulary ORDER BY word")
    data = c.fetchall()
    conn.close()
    return render_template_string(VOCAB_TEMPLATE, data=data)

@app.route('/admin/add_vocab', methods=['POST'])
@login_required
def admin_add_vocab():
    word = request.form['word']
    meaning = request.form['meaning']
    example = request.form.get('example', '')
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    try:
        c.execute("INSERT INTO vocabulary (word, meaning, example) VALUES (?, ?, ?)", (word.lower(), meaning, example))
        conn.commit()
    except:
        pass
    conn.close()
    return redirect('/admin/vocabulary')

@app.route('/admin/delete_vocab/<int:id>')
@login_required
def admin_delete_vocab(id):
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("DELETE FROM vocabulary WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return redirect('/admin/vocabulary')

# ========== 統計專有名詞管理 ==========
@app.route('/admin/statistics')
@login_required
def admin_statistics():
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("SELECT id, term, translation, definition, code FROM statistics_glossary ORDER BY term")
    data = c.fetchall()
    conn.close()
    return render_template_string(STATISTICS_TEMPLATE, data=data)

@app.route('/admin/add_statistics', methods=['POST'])
@login_required
def admin_add_statistics():
    term = request.form['term']
    translation = request.form['translation']
    definition = request.form['definition']
    code = request.form.get('code', '')
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    try:
        c.execute("INSERT INTO statistics_glossary (term, translation, definition, code) VALUES (?, ?, ?, ?)", 
                  (term, translation, definition, code))
        conn.commit()
    except:
        pass
    conn.close()
    return redirect('/admin/statistics')

@app.route('/admin/delete_statistics/<int:id>')
@login_required
def admin_delete_statistics(id):
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("DELETE FROM statistics_glossary WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return redirect('/admin/statistics')

# ========== 運動社會學專有名詞管理 ==========
@app.route('/admin/sociology')
@login_required
def admin_sociology():
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("SELECT id, term, translation, definition FROM sociology_glossary ORDER BY term")
    data = c.fetchall()
    conn.close()
    return render_template_string(SOCIOLOGY_TEMPLATE, data=data)

@app.route('/admin/add_sociology', methods=['POST'])
@login_required
def admin_add_sociology():
    term = request.form['term']
    translation = request.form['translation']
    definition = request.form['definition']
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    try:
        c.execute("INSERT INTO sociology_glossary (term, translation, definition) VALUES (?, ?, ?)", 
                  (term, translation, definition))
        conn.commit()
    except:
        pass
    conn.close()
    return redirect('/admin/sociology')

@app.route('/admin/delete_sociology/<int:id>')
@login_required
def admin_delete_sociology(id):
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("DELETE FROM sociology_glossary WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return redirect('/admin/sociology')

# ========== 探索教育專有名詞管理 ==========
@app.route('/admin/outdoor')
@login_required
def admin_outdoor():
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("SELECT id, term, translation, definition FROM outdoor_glossary ORDER BY term")
    data = c.fetchall()
    conn.close()
    return render_template_string(OUTDOOR_TEMPLATE, data=data)

@app.route('/admin/add_outdoor', methods=['POST'])
@login_required
def admin_add_outdoor():
    term = request.form['term']
    translation = request.form['translation']
    definition = request.form['definition']
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    try:
        c.execute("INSERT INTO outdoor_glossary (term, translation, definition) VALUES (?, ?, ?)", 
                  (term, translation, definition))
        conn.commit()
    except:
        pass
    conn.close()
    return redirect('/admin/outdoor')

@app.route('/admin/delete_outdoor/<int:id>')
@login_required
def admin_delete_outdoor(id):
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("DELETE FROM outdoor_glossary WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return redirect('/admin/outdoor')

# ========== 待辦事項管理 ==========
@app.route('/admin/todos')
@login_required
def admin_todos():
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("SELECT id, user_id, task, todo_date, status FROM todos ORDER BY todo_date DESC LIMIT 100")
    data = c.fetchall()
    conn.close()
    return render_template_string(TODOS_TEMPLATE, data=data)

@app.route('/admin/delete_todo/<int:id>')
@login_required
def admin_delete_todo(id):
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("DELETE FROM todos WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return redirect('/admin/todos')

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
            <a href="/admin/statistics" style="display: block; padding: 15px; background: #2ecc71; color: white; text-decoration: none; border-radius: 8px;">📊 實驗設計與統計 - 專有名詞管理</a>
            <a href="/admin/sociology" style="display: block; padding: 15px; background: #e74c3c; color: white; text-decoration: none; border-radius: 8px;">⚽ 運動社會學 - 專有名詞管理</a>
            <a href="/admin/outdoor" style="display: block; padding: 15px; background: #f39c12; color: white; text-decoration: none; border-radius: 8px;">🏕️ 探索教育 - 專有名詞管理</a>
            <a href="/admin/todos" style="display: block; padding: 15px; background: #9b59b6; color: white; text-decoration: none; border-radius: 8px;">✅ 待辦事項管理</a>
        </div>
    </div>
</body>
</html>
'''

VOCAB_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head><title>英文單字管理</title><meta charset="UTF-8"></head>
<body style="font-family: Arial; padding: 20px;">
    <h1>📚 英文單字管理</h1>
    <p><a href="/admin">← 返回首頁</a> | <a href="/logout">登出</a></p>
    
    <div style="margin: 20px 0; padding: 15px; background: #f0f0f0;">
        <h3>➕ 新增單字</h3>
        <form method="post" action="/admin/add_vocab">
            <input type="text" name="word" placeholder="英文單字" required>
            <input type="text" name="meaning" placeholder="中文意思" required>
            <input type="text" name="example" placeholder="例句" style="width: 300px;">
            <button type="submit">新增</button>
        </form>
    </div>
    
    <table border="1" cellpadding="8" style="border-collapse: collapse; width: 100%;">
        <tr><th>ID</th><th>單字</th><th>意思</th><th>例句</th><th>操作</th></tr>
        {% for row in data %}
        <tr>
            <td>{{ row[0] }}</td>
            <td><strong>{{ row[1] }}</strong></td>
            <td>{{ row[2] }}</td>
            <td>{{ row[3] }}</td>
            <td><a href="/admin/delete_vocab/{{ row[0] }}" onclick="return confirm('確定刪除？')">刪除</a></td>
        </tr>
        {% endfor %}
    </table>
</body>
</html>
'''

STATISTICS_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head><title>統計專有名詞管理</title><meta charset="UTF-8"></head>
<body style="font-family: Arial; padding: 20px;">
    <h1>📊 實驗設計與統計 - 專有名詞管理</h1>
    <p><a href="/admin">← 返回首頁</a> | <a href="/logout">登出</a></p>
    
    <div style="margin: 20px 0; padding: 15px; background: #f0f0f0;">
        <h3>➕ 新增專有名詞</h3>
        <form method="post" action="/admin/add_statistics">
            <input type="text" name="term" placeholder="英文/名詞" required style="width: 200px;">
            <input type="text" name="translation" placeholder="中文翻譯" required style="width: 150px;">
            <input type="text" name="definition" placeholder="解釋" required style="width: 300px;">
            <textarea name="code" placeholder="Python 程式碼" rows="3" style="width: 100%;"></textarea>
            <button type="submit">新增</button>
        </form>
    </div>
    
    <table border="1" cellpadding="8" style="border-collapse: collapse; width: 100%;">
        <tr><th>ID</th><th>英文/名詞</th><th>中文翻譯</th><th>解釋</th><th>程式碼</th><th>操作</th></tr>
        {% for row in data %}
        <tr>
            <td>{{ row[0] }}</td>
            <td><strong>{{ row[1] }}</strong></td>
            <td>{{ row[2] }}</td>
            <td>{{ row[3][:50] }}{% if row[3]|length > 50 %}...{% endif %}</td>
            <td>{{ row[4][:30] if row[4] else '-' }}</td>
            <td><a href="/admin/delete_statistics/{{ row[0] }}" onclick="return confirm('確定刪除？')">刪除</a></td>
        </tr>
        {% endfor %}
    </table>
</body>
</html>
'''

SOCIOLOGY_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head><title>運動社會學專有名詞管理</title><meta charset="UTF-8"></head>
<body style="font-family: Arial; padding: 20px;">
    <h1>⚽ 運動社會學 - 專有名詞管理</h1>
    <p><a href="/admin">← 返回首頁</a> | <a href="/logout">登出</a></p>
    
    <div style="margin: 20px 0; padding: 15px; background: #f0f0f0;">
        <h3>➕ 新增專有名詞</h3>
        <form method="post" action="/admin/add_sociology">
            <input type="text" name="term" placeholder="英文/名詞" required style="width: 250px;">
            <input type="text" name="translation" placeholder="中文翻譯" required style="width: 150px;">
            <textarea name="definition" placeholder="解釋" required rows="2" style="width: 100%;"></textarea>
            <button type="submit">新增</button>
        </form>
    </div>
    
    <table border="1" cellpadding="8" style="border-collapse: collapse; width: 100%;">
        <tr><th>ID</th><th>英文/名詞</th><th>中文翻譯</th><th>解釋</th><th>操作</th></tr>
        {% for row in data %}
        <tr>
            <td>{{ row[0] }}</td>
            <td><strong>{{ row[1] }}</strong></td>
            <td>{{ row[2] }}</td>
            <td>{{ row[3][:60] }}{% if row[3]|length > 60 %}...{% endif %}</td>
            <td><a href="/admin/delete_sociology/{{ row[0] }}" onclick="return confirm('確定刪除？')">刪除</a></td>
        </tr>
        {% endfor %}
    </table>
</body>
</html>
'''

OUTDOOR_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head><title>探索教育專有名詞管理</title><meta charset="UTF-8"></head>
<body style="font-family: Arial; padding: 20px;">
    <h1>🏕️ 探索教育 - 專有名詞管理</h1>
    <p><a href="/admin">← 返回首頁</a> | <a href="/logout">登出</a></p>
    
    <div style="margin: 20px 0; padding: 15px; background: #f0f0f0;">
        <h3>➕ 新增專有名詞</h3>
        <form method="post" action="/admin/add_outdoor">
            <input type="text" name="term" placeholder="英文/名詞" required style="width: 250px;">
            <input type="text" name="translation" placeholder="中文翻譯" required style="width: 150px;">
            <textarea name="definition" placeholder="解釋" required rows="2" style="width: 100%;"></textarea>
            <button type="submit">新增</button>
        </form>
    </div>
    
    <table border="1" cellpadding="8" style="border-collapse: collapse; width: 100%;">
        <table><th>ID</th><th>英文/名詞</th><th>中文翻譯</th><th>解釋</th><th>操作</th></tr>
        {% for row in data %}
        <tr>
            <td>{{ row[0] }}</td>
            <td><strong>{{ row[1] }}</strong></td>
            <td>{{ row[2] }}</td>
            <td>{{ row[3][:60] }}{% if row[3]|length > 60 %}...{% endif %}</td>
            <td><a href="/admin/delete_outdoor/{{ row[0] }}" onclick="return confirm('確定刪除？')">刪除</a></td>
        </tr>
        {% endfor %}
    </table>
</body>
</html>
'''

TODOS_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head><title>待辦事項管理</title><meta charset="UTF-8"></head>
<body style="font-family: Arial; padding: 20px;">
    <h1>✅ 待辦事項管理</h1>
    <p><a href="/admin">← 返回首頁</a> | <a href="/logout">登出</a></p>
    
    <table border="1" cellpadding="8" style="border-collapse: collapse; width: 100%;">
        <tr><th>ID</th><th>使用者ID</th><th>任務</th><th>日期</th><th>狀態</th><th>操作</th></tr>
        {% for row in data %}
        <tr>
            <td>{{ row[0] }}</td>
            <td>{{ row[1][:20] }}...</td>
            <td>{{ row[2] }}</td>
            <td>{{ row[3] }}</td>
            <td>{% if row[4] == 'pending' %}⏳ 進行中{% else %}✅ 已完成{% endif %}</td>
            <td><a href="/admin/delete_todo/{{ row[0] }}" onclick="return confirm('確定刪除？')">刪除</a></td>
        </tr>
        {% endfor %}
    </table>
</body>
</html>
'''

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
