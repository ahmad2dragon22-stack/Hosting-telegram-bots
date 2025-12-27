import os
import signal
import subprocess
import logging
import sys
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# إعداد السجلات (Logs)
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- الإعدادات ---
ADMIN_ID = 8049455831 # استبدل هذا بـ ID حسابك في تيليجرام
BOT_TOKEN = "8328934625:AAEKHcqH7jbizVE6iByqIOikVpEVmshbwr0"  # توكن البوت الرئيسي
BOTS_DIR = "hosted_bots"  # المجلد الذي ستحفظ فيه البوتات

if not os.path.exists(BOTS_DIR):
    os.makedirs(BOTS_DIR)

# قاموس لتخزين العمليات المشغلة (Process ID: Process Object)
running_bots = {}

# --- الوظائف المساعدة ---

def start_bot_process(file_path, bot_name):
    """تشغيل ملف البوت كعملية فرعية والتقاط الأخطاء"""
    try:
        # تشغيل البوت وربط المخرجات والأخطاء
        process = subprocess.Popen(
            [sys.executable, file_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        running_bots[bot_name] = {
            "process": process,
            "path": file_path
        }
        return True, None
    except Exception as e:
        return False, str(e)

# --- أوامر البوت الرئيسي ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    
    await update.message.reply_text(
        "👋 أهلاً بك في مدير استضافة البوتات.\n\n"
        "🔸 ارفع ملف بصيغة `.py` لتشغيله.\n"
        "🔸 استخدم /dashboard لإدارة البوتات المشغلة."
    )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    doc = update.message.document
    if not doc.file_name.endswith('.py'):
        await update.message.reply_text("❌ يرجى رفع ملفات Python فقط (.py)")
        return

    file_path = os.path.join(BOTS_DIR, doc.file_name)
    
    # تحميل الملف
    new_file = await context.bot.get_file(doc.file_id)
    await new_file.download_to_drive(file_path)

    await update.message.reply_text(f"📥 تم استلام {doc.file_name}. جاري التشغيل...")
    
    success, error = start_bot_process(file_path, doc.file_name)
    
    if success:
        await update.message.reply_text(f"✅ تم تشغيل {doc.file_name} بنجاح!")
    else:
        await update.message.reply_text(f"❌ فشل التشغيل:\n`{error}`", parse_mode='Markdown')

async def dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not running_bots:
        await update.message.reply_text("📭 لا توجد بوتات مشغلة حالياً.")
        return

    keyboard = []
    for bot_name in running_bots.keys():
        keyboard.append([InlineKeyboardButton(f"🛑 إيقاف {bot_name}", callback_data=f"stop_{bot_name}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🖥 لوحة التحكم بالبوتات المشغلة:", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data.startswith("stop_"):
        bot_name = query.data.replace("stop_", "")
        if bot_name in running_bots:
            process = running_bots[bot_name]["process"]
            process.terminate() # إيقاف البوت
            del running_bots[bot_name]
            await query.edit_message_text(f"⛔ تم إيقاف البوت: {bot_name}")
        else:
            await query.edit_message_text("⚠️ البوت متوقف بالفعل أو غير موجود.")

async def check_errors(context: ContextTypes.DEFAULT_TYPE):
    """وظيفة دورية للتحقق من الأخطاء في البوتات المشغلة"""
    for bot_name, data in list(running_bots.items()):
        process = data["process"]
        # التحقق إذا توقفت العملية فجأة
        poll = process.poll()
        if poll is not None:
            # العملية توقفت، قراءة الخطأ
            _, stderr = process.communicate()
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"🚨 البوت `{bot_name}` توقف عن العمل!\n\n**الخطأ:**\n`{stderr}`",
                parse_mode='Markdown'
            )
            del running_bots[bot_name]

def main():
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("dashboard", dashboard))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(CallbackQueryHandler(button_handler))

    # فحص الأخطاء كل 30 ثانية
    job_queue = application.job_queue
    job_queue.run_repeating(check_errors, interval=30, first=10)

    print("Main Hosting Bot is running...")
    application.run_polling()

if __name__ == '__main__':
    main()