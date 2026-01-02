import telebot
from telebot import types
import os
import subprocess
import sqlite3
import signal
import time
from datetime import datetime

# --- الإعدادات الثابتة ---
API_TOKEN = '8328934625:AAFsvlzSvZXOkIhgoIWsp1hWUEyrfExr24c'
bot = telebot.TeleBot(API_TOKEN)
DB_PATH = "hosting_pro.db"
BASE_HOST_DIR = "hosted_bots"

# تهيئة البيئة
if not os.path.exists(BASE_HOST_DIR):
    os.makedirs(BASE_HOST_DIR)

# --- نظام قاعدة البيانات المحسن ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_bots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            bot_display_name TEXT,
            internal_filename TEXT,
            status TEXT DEFAULT 'stopped',
            start_time TEXT DEFAULT 'N/A'
        )
    ''')
    conn.commit()
    conn.close()

init_db()
# قاموس لتتبع العمليات المشغلة خلال الجلسة الحالية
running_processes = {}

# --- دوال الأزرار (Markup) ---

def get_main_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🚀 رفع بوت جديد", callback_data="nav_upload"),
        types.InlineKeyboardButton("💻 لوحة التحكم", callback_data="nav_dashboard"),
        types.InlineKeyboardButton("⚙️ الإعدادات", callback_data="nav_settings"),
        types.InlineKeyboardButton("📊 الإحصائيات", callback_data="nav_stats")
    )
    return markup

def get_dashboard_markup(user_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT bot_display_name, status FROM user_bots WHERE user_id = ?", (user_id,))
    bots = cursor.fetchall()
    conn.close()

    if not bots:
        markup.add(types.InlineKeyboardButton("❌ لا يوجد بوتات مرفوعة", callback_data="none"))
    else:
        for name, status in bots:
            indicator = "🟢" if status == "running" else "🔴"
            markup.add(types.InlineKeyboardButton(f"{indicator} {name}", callback_data=f"manage:{name}"))
    
    markup.add(types.InlineKeyboardButton("🔙 العودة للقائمة", callback_data="nav_home"))
    return markup

def get_manage_markup(bot_name, status):
    markup = types.InlineKeyboardMarkup(row_width=2)
    if status == "running":
        markup.add(types.InlineKeyboardButton("🛑 إيقاف التشغيل", callback_data=f"exec:stop:{bot_name}"))
    else:
        markup.add(types.InlineKeyboardButton("▶️ بدء التشغيل", callback_data=f"exec:start:{bot_name}"))
    
    markup.add(
        types.InlineKeyboardButton("🗑 حذف البوت", callback_data=f"exec:delete:{bot_name}"),
        types.InlineKeyboardButton("🔄 تحديث الحالة", callback_data=f"manage:{bot_name}")
    )
    markup.add(types.InlineKeyboardButton("🔙 العودة للوحة التحكم", callback_data="nav_dashboard"))
    return markup

# --- معالجة الأوامر ---

@bot.message_handler(commands=['start'])
def start(message):
    welcome_text = (
        f"🤖 **مرحباً بك في نظام الاستضافة الاحترافي**\n\n"
        f"عزيزي {message.from_user.first_name}، يمكنك هنا رفع وإدارة بوتاتك بسهولة.\n"
        "استخدم الأزرار أدناه للبدء."
    )
    bot.send_message(message.chat.id, welcome_text, reply_markup=get_main_menu(), parse_mode="Markdown")

# --- معالجة ضغطات الأزرار (Callback Query) ---

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    user_id = call.from_user.id
    data = call.data

    # التنقل الأساسي
    if data == "nav_home":
        bot.edit_message_text("القائمة الرئيسية:", call.message.chat.id, call.message.message_id, reply_markup=get_main_menu())
    
    elif data == "nav_upload":
        msg = bot.send_message(call.message.chat.id, "📥 **من فضلك أرسل ملف البوت الآن (.py):**")
        bot.register_next_step_handler(msg, process_file_upload)
    
    elif data == "nav_dashboard":
        bot.edit_message_text("💻 **لوحة التحكم ببوتاتك:**\nاضغط على اسم البوت لإدارته.", call.message.chat.id, call.message.message_id, reply_markup=get_dashboard_markup(user_id))

    elif data == "nav_stats":
        conn = sqlite3.connect(DB_PATH)
        res = conn.execute("SELECT COUNT(*) FROM user_bots WHERE user_id = ?", (user_id,)).fetchone()
        conn.close()
        bot.answer_callback_query(call.id, f"لديك {res[0]} بوتات في نظامنا", show_alert=True)

    elif data == "nav_settings":
        settings_text = "⚙️ **إعدادات الحساب الاستضافي:**\n\nيمكنك من هنا التحكم في تفضيلاتك العامة."
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🗑 مسح كافة البيانات", callback_data="exec:wipe_all"))
        markup.add(types.InlineKeyboardButton("🔙 عودة", callback_data="nav_home"))
        bot.edit_message_text(settings_text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

    # إدارة البوتات الفردية
    elif data.startswith("manage:"):
        bot_name = data.split(":")[1]
        conn = sqlite3.connect(DB_PATH)
        bot_data = conn.execute("SELECT status, start_time FROM user_bots WHERE user_id = ? AND bot_display_name = ?", (user_id, bot_name)).fetchone()
        conn.close()
        
        if bot_data:
            status, start_time = bot_data
            status_text = "🟢 يعمل حالياً" if status == "running" else "🔴 متوقف"
            msg_text = f"🤖 **إدارة البوت:** `{bot_name}`\n\n📊 الحالة: {status_text}\n⏰ وقت البدء: `{start_time}`"
            bot.edit_message_text(msg_text, call.message.chat.id, call.message.message_id, reply_markup=get_manage_markup(bot_name, status), parse_mode="Markdown")

    # تنفيذ العمليات (تشغيل، إيقاف، حذف)
    elif data.startswith("exec:"):
        parts = data.split(":")
        action = parts[1]
        
        if action == "wipe_all":
            wipe_user_data(user_id)
            bot.answer_callback_query(call.id, "تم مسح كافة البيانات بنجاح")
            bot.edit_message_text("تمت إعادة ضبط حسابك.", call.message.chat.id, call.message.message_id, reply_markup=get_main_menu())
            return

        bot_name = parts[2]
        handle_bot_action(call, action, bot_name)

# --- الوظائف الجوهرية ---

def process_file_upload(message):
    if not message.document or not message.document.file_name.endswith('.py'):
        bot.send_message(message.chat.id, "❌ خطأ: يجب إرسال ملف بصيغة `.py` فقط.")
        return

    user_id = message.from_user.id
    display_name = message.document.file_name
    internal_name = f"{user_id}_{int(time.time())}_{display_name}"
    file_path = os.path.join(BASE_HOST_DIR, internal_name)

    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        with open(file_path, 'wb') as f:
            f.write(downloaded)
        
        conn = sqlite3.connect(DB_PATH)
        conn.execute("INSERT INTO user_bots (user_id, bot_display_name, internal_filename) VALUES (?, ?, ?)", 
                    (user_id, display_name, internal_name))
        conn.commit()
        conn.close()
        
        bot.send_message(message.chat.id, f"✅ تم استلام البوت `{display_name}` بنجاح!\nاذهب للوحة التحكم لتشغيله.", parse_mode="Markdown", reply_markup=get_main_menu())
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ حدث خطأ أثناء الحفظ: {e}")

def handle_bot_action(call, action, bot_name):
    user_id = call.from_user.id
    conn = sqlite3.connect(DB_PATH)
    res = conn.execute("SELECT internal_filename, status FROM user_bots WHERE user_id = ? AND bot_display_name = ?", (user_id, bot_name)).fetchone()
    
    if not res:
        bot.answer_callback_query(call.id, "خطأ: لم يتم العثور على البيانات")
        conn.close()
        return

    internal_name, status = res
    file_path = os.path.join(BASE_HOST_DIR, internal_name)
    proc_key = f"{user_id}_{bot_name}"

    if action == "start":
        if status == "running":
            bot.answer_callback_query(call.id, "البوت يعمل بالفعل!")
        else:
            try:
                # تشغيل البوت في عملية مستقلة
                new_proc = subprocess.Popen(['python', file_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                running_processes[proc_key] = new_proc
                start_time = datetime.now().strftime("%Y-%m-%d %H:%M")
                conn.execute("UPDATE user_bots SET status='running', start_time=? WHERE user_id=? AND bot_display_name=?", (start_time, user_id, bot_name))
                bot.answer_callback_query(call.id, "🚀 انطلق البوت بنجاح!")
            except Exception as e:
                bot.answer_callback_query(call.id, f"فشل التشغيل: {e}", show_alert=True)

    elif action == "stop":
        if proc_key in running_processes:
            running_processes[proc_key].terminate()
            del running_processes[proc_key]
        
        conn.execute("UPDATE user_bots SET status='stopped', start_time='N/A' WHERE user_id=? AND bot_display_name=?", (user_id, bot_name))
        bot.answer_callback_query(call.id, "🛑 تم إيقاف البوت")

    elif action == "delete":
        if proc_key in running_processes:
            running_processes[proc_key].terminate()
            del running_processes[proc_key]
        
        conn.execute("DELETE FROM user_bots WHERE user_id=? AND bot_display_name=?", (user_id, bot_name))
        if os.path.exists(file_path):
            os.remove(file_path)
        bot.answer_callback_query(call.id, "🗑 تم حذف البوت نهائياً")
        conn.commit()
        conn.close()
        bot.edit_message_text("💻 لوحة التحكم:", call.message.chat.id, call.message.message_id, reply_markup=get_dashboard_markup(user_id))
        return

    conn.commit()
    conn.close()
    # تحديث واجهة الإدارة بعد التغيير
    handle_callbacks(types.CallbackQuery(id=call.id, from_user=call.from_user, chat_instance=call.chat_instance, message=call.message, data=f"manage:{bot_name}"))

def wipe_user_data(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT internal_filename, bot_display_name FROM user_bots WHERE user_id = ?", (user_id,))
    bots = cursor.fetchall()
    
    for internal, display in bots:
        proc_key = f"{user_id}_{display}"
        if proc_key in running_processes:
            running_processes[proc_key].terminate()
            del running_processes[proc_key]
        
        file_path = os.path.join(BASE_HOST_DIR, internal)
        if os.path.exists(file_path):
            os.remove(file_path)
    
    cursor.execute("DELETE FROM user_bots WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

# تشغيل البوت
if __name__ == "__main__":
    print("✅ System Online: Smart Host Pro is running...")
    bot.infinity_polling()