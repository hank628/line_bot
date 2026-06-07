from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, TextMessage,
    QuickReply, QuickReplyItem, MessageAction
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, FollowEvent
import os
import sqlite3
import random

# ========== 設定 ==========
CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")

app = Flask(__name__)
configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# ========== 初始化資料庫 ==========
def init_db():
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    
    # 建立統計資料表
    c.execute('''CREATE TABLE IF NOT EXISTS glossary_stats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        term TEXT UNIQUE,
        translation TEXT,
        definition TEXT,
        code TEXT
    )''')
    
    # 檢查是否有資料，沒有的話就新增
    c.execute("SELECT COUNT(*) FROM glossary_stats")
    if c.fetchone()[0] == 0:
        default_stats = [
            ("t-test", "t檢定", "比較兩組樣本平均數是否有顯著差異", "from scipy import stats\nt_stat, p_value = stats.ttest_ind(group1, group2)"),
            ("ANOVA", "變異數分析", "比較三組以上樣本平均數是否有顯著差異", "from scipy import stats\nf_stat, p_value = stats.f_oneway(group1, group2, group3)"),
            ("correlation", "相關分析", "探討兩個連續變數之間的線性關係強度", "from scipy import stats\nr, p_value = stats.pearsonr(x, y)"),
        ]
        c.executemany("INSERT INTO glossary_stats (term, translation, definition, code) VALUES (?, ?, ?, ?)", default_stats)
        print("✅ 已寫入統計名詞")
    
    conn.commit()
    
    # 驗證
    c.execute("SELECT COUNT(*) FROM glossary_stats")
    count = c.fetchone()[0]
    print(f"📊 統計名詞筆數: {count}")
    
    conn.close()
    print("✅ 資料庫初始化完成")

init_db()

# ========== 按鈕選單 ==========
def get_main_quick_reply():
    return QuickReply(
        items=[
            QuickReplyItem(action=MessageAction(label="📊統計", text="統計")),
            QuickReplyItem(action=MessageAction(label="📚英字", text="單字")),
            QuickReplyItem(action=MessageAction(label="✅待辦", text="待辦")),
            QuickReplyItem(action=MessageAction(label="🆔取得ID", text="取得我的ID")),
        ]
    )

# ========== 查詢函數 ==========
def get_stats_list():
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("SELECT id, term, translation FROM glossary_stats ORDER BY id")
    results = c.fetchall()
    conn.close()
    return results

def get_stats_detail(term_id):
    conn = sqlite3.connect('course_bot.db')
    c = conn.cursor()
    c.execute("SELECT term, translation, definition, code FROM glossary_stats WHERE id = ?", (term_id,))
    result = c.fetchone()
    conn.close()
    return result

def get_random_vocab():
    return ("apple", "蘋果 🍎", "I eat an apple every day.")

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
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text="🤖 歡迎使用 HANK EduMentor！\n\n點擊下方按鈕：", quick_reply=get_main_quick_reply())]
            )
        )

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    msg = event.message.text.strip()
    msg_lower = msg.lower()
    user_id = event.source.user_id
    
    # 統計
    if msg_lower in ["統計", "statistics"]:
        stats_list = get_stats_list()
        if stats_list:
            text = "📊 統計專有名詞\n\n"
            for i, (sid, term, trans) in enumerate(stats_list, 1):
                text += f"{i}. {term} - {trans}\n"
            text += "\n💡 輸入數字查詳細（如：1）"
            reply = TextMessage(text=text, quick_reply=get_main_quick_reply())
        else:
            reply = TextMessage(text="📊 暫無統計資料\n\n請檢查資料庫", quick_reply=get_main_quick_reply())
    
    # 數字查詢
    elif msg_lower.isdigit():
        num = int(msg_lower)
        stats_list = get_stats_list()
        if 1 <= num <= len(stats_list):
            detail = get_stats_detail(stats_list[num-1][0])
            if detail:
                term, trans, definition, code = detail
                text = f"📖 **{term}**\n🀄️ {trans}\n📝 {definition}"
                if code:
                    text += f"\n\n💻 程式碼：\n```\n{code}\n```"
                reply = TextMessage(text=text, quick_reply=get_main_quick_reply())
            else:
                reply = TextMessage(text="查無資料", quick_reply=get_main_quick_reply())
        else:
            reply = TextMessage(text=f"請輸入 1-{len(stats_list)} 之間的數字", quick_reply=get_main_quick_reply())
    
    # 英文單字
    elif msg_lower in ["單字", "english", "vocab"]:
        word, meaning, example = get_random_vocab()
        text = f"📖 {word} = {meaning}\n📝 例句：{example}"
        reply = TextMessage(text=text, quick_reply=get_main_quick_reply())
    
    # 待辦
    elif msg_lower in ["待辦", "待辦事項", "todo"]:
        reply = TextMessage(text="✅ 待辦功能測試中\n\n你輸入的訊息：" + msg, quick_reply=get_main_quick_reply())
    
    # 取得 ID
    elif "取得我的id" in msg_lower or "取得id" in msg_lower or "myid" in msg_lower:
        reply = TextMessage(text=f"🔑 你的 LINE User ID 是：\n{user_id}", quick_reply=get_main_quick_reply())
    
    # 幫助
    elif msg_lower in ["幫助", "選單", "menu", "help"]:
        reply = TextMessage(text="🤖 請點擊下方按鈕：", quick_reply=get_main_quick_reply())
    
    else:
        reply = TextMessage(
            text=f"你說了：「{msg}」\n\n點擊下方按鈕：",
            quick_reply=get_main_quick_reply()
        )
    
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(reply_token=event.reply_token, messages=[reply])
        )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
