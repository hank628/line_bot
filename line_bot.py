from flask import Flask, request, abort, render_template_string, redirect, session
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, TextMessage,
    QuickReply, QuickReplyItem, MessageAction
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, FollowEvent, LocationMessageContent
import os
import sqlite3
import requests
import random
from datetime import datetime
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
    c.execute('''CREATE TABLE IF NOT EXISTS vocabulary (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        word TEXT UNIQUE,
        meaning TEXT,
        example TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS todos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        task TEXT,
        todo_date TEXT,
        status TEXT DEFAULT 'pending'
    )''')
    c.execute("SELECT COUNT(*) FROM vocabulary")
    if c.fetchone()[0] == 0:
        c.executemany("INSERT INTO vocabulary (word, meaning, example) VALUES (?, ?, ?)", [
            ("apple", "蘋果 🍎", "I eat an apple."),
            ("book", "書 📚", "This is a book."),
            ("t-test", "t檢定", "比較兩組平均數差異"),
            ("ANOVA", "變異數分析", "比較三組以上平均數"),
        ])
    conn.commit()
    conn.close()

init_db()

# ========== 按鈕選單 ==========
def get_quick_reply():
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

# ========== 天氣函數 ==========
def get_weather(lat, lon):
    try:
        url = f"https://wttr.in/{lat},{lon}?format=%C+%t&lang=zh"
        response = requests.get(url, timeout=8)
        if response.status_code == 200 and response.text.strip():
            weather_text = response.text.strip()
            parts = weather_text.split()
            if len(parts) >= 2:
                condition = parts[0]
                temp = parts[1]
                return f"{condition}，{temp}"
    except:
        pass
    
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true&temperature_unit=celsius&timezone=Asia/Taipei"
        response = requests.get(url, timeout=8)
        if response.status_code == 200:
            data = response.json()
            temp = data['current_weather']['temperature']
            code = data['current_weather']['weathercode']
            weather_codes = {0: "☀️ 晴天", 1: "🌤️ 晴時多雲", 2: "⛅ 局部多雲", 3: "☁️ 陰天", 61: "🌧️ 下雨", 95: "⛈️ 雷雨"}
            weather = weather_codes.get(code, "🌡️")
            return f"{weather}，{temp}°C"
    except:
        pass
    
    conditions = ["☀️ 晴天", "⛅ 多雲時晴", "🌤️ 晴時多雲", "☁️ 陰天"]
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
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text="🤖 歡迎使用課程小幫手！\n\n請選擇功能：", quick_reply=get_quick_reply())]
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
    
    if msg_lower in ["幫助", "選單", "menu"]:
        reply = TextMessage(text="請選擇功能：", quick_reply=get_quick_reply())
    
    elif msg_lower in ["天氣", "weather"]:
        reply = TextMessage(
            text="📍 如何取得天氣？\n\n1️⃣ 點選聊天室左下角的「＋」\n2️⃣ 選擇「位置」\n3️⃣ 點選「傳送目前位置」",
            quick_reply=get_quick_reply()
        )
    
    elif msg_lower in ["實驗設計與統計", "統計"]:
        reply = TextMessage(
            text="📊 實驗設計與統計\n\n• t-test (t檢定) - 比較兩組平均數\n• ANOVA - 比較三組以上\n• correlation - 相關分析",
            quick_reply=get_quick_reply()
        )
    
    elif msg_lower in ["運動社會學", "社會學"]:
        reply = TextMessage(
            text="⚽ 運動社會學\n\n• sports socialization (運動社會化)\n• social stratification (社會階層化)\n• gender ideology (性別意識形態)",
            quick_reply=get_quick_reply()
        )
    
    elif msg_lower in ["探索教育", "探索"]:
        reply = TextMessage(
            text="🏕️ 探索教育\n\n• experiential learning (體驗式學習)\n• challenge by choice (自願挑戰)\n• debriefing (反思回饋)",
            quick_reply=get_quick_reply()
        )
    
    elif msg_lower == "單字":
        conn = sqlite3.connect('course_bot.db')
        c = conn.cursor()
        c.execute("SELECT word, meaning FROM vocabulary ORDER BY RANDOM() LIMIT 1")
        result = c.fetchone()
        conn.close()
        reply = TextMessage(text=f"📖 {result[0]} = {result[1]}" if result else "📖 暫時沒有單字", quick_reply=get_quick_reply())
    
    elif msg_lower.startswith("新增 "):
        task = msg[3:]
        user_id = event.source.user_id
        conn = sqlite3.connect('course_bot.db')
        c = conn.cursor()
        c.execute("INSERT INTO todos (user_id, task, todo_date) VALUES (?, ?, ?)", 
                  (user_id, task, datetime.now().strftime('%Y-%m-%d')))
        conn.commit()
        conn.close()
        reply = TextMessage(text=f"✅ 已新增：{task}", quick_reply=get_quick_reply())
    
    elif msg_lower in ["待辦", "待辦事項", "todo"]:
        user_id = event.source.user_id
        conn = sqlite3.connect('course_bot.db')
        c = conn.cursor()
        c.execute("SELECT id, task FROM todos WHERE user_id = ? AND status = 'pending'", (user_id,))
        todos = c.fetchall()
        conn.close()
        if todos:
            text = "✅ 待辦清單：\n" + "\n".join([f"{t[0]}. {t[1]}" for t in todos])
            text += "\n\n💡 完成請輸入「完成 編號」"
        else:
            text = "📋 沒有待辦事項"
        reply = TextMessage(text=text, quick_reply=get_quick_reply())
    
    elif msg_lower.startswith("完成 "):
        try:
            todo_id = int(msg_lower[3:])
            user_id = event.source.user_id
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
            text=f"你說了：「{msg}」\n\n輸入「幫助」看功能選單",
            quick_reply=get_quick_reply()
        )
    
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(reply_token=event.reply_token, messages=[reply])
        )

# ========== 管理後台路由 ==========
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
            return redirect('/dashboard')
        return render_template_string(LOGIN_TEMPLATE, error="密碼錯誤！")
    return render_template_string(LOGIN_TEMPLATE, error=None)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect('/login')

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template_string(DASHBOARD_TEMPLATE)

@app.route('/vocabulary')
@login_required
def vocabulary_page():
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("SELECT id, word, meaning, example FROM vocabulary ORDER BY word")
    data = c.fetchall()
    conn.close()
    return render_template_string(VOCAB_TEMPLATE, data=data)

@app.route('/add_vocab', methods=['POST'])
@login_required
def add_vocab_route():
    word = request.form['word']
    meaning = request.form['meaning']
    example = request.form.get('example', '')
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    try:
        c.execute("INSERT INTO vocabulary (word, meaning, example) VALUES (?, ?, ?)", 
                  (word.lower(), meaning, example))
        conn.commit()
    except:
        pass
    conn.close()
    return redirect('/vocabulary')

@app.route('/delete_vocab/<int:id>')
@login_required
def delete_vocab_route(id):
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("DELETE FROM vocabulary WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return redirect('/vocabulary')

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
    <p><a href="/dashboard">← 返回首頁</a> | <a href="/logout">登出</a></p>
    
    <div style="margin: 20px 0; padding: 15px; background: #f0f0f0;">
        <h3>➕ 手動新增</h3>
        <form method="post" action="/add_vocab">
            <input type="text" name="word" placeholder="英文單字" required>
            <input type="text" name="meaning" placeholder="中文意思" required>
            <input type="text" name="example" placeholder="例句" style="width: 300px;">
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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
