import os
import signal
import subprocess
import logging
import sys
import asyncio
import json
import time
import urllib.parse
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# إعداد السجلات (Logs)
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- الإعدادات ---
VERSION = "1.2.0"
DEFAULT_ADMIN_ID = 8049455831 # استبدل هذا بـ ID حسابك في تيليجرام
DEFAULT_BOT_TOKEN = "8328934625:AAEKHcqH7jbizVE6iByqIOikVpEVmshbwr0"

# اقرأ متغيرات البيئة أولاً ثم استخدم القيم الافتراضية
BOT_TOKEN = os.getenv("BOT_TOKEN", DEFAULT_BOT_TOKEN)
ADMIN_ID = int(os.getenv("ADMIN_ID", DEFAULT_ADMIN_ID))

BASE_DIR = Path(os.getenv("BASE_DIR", os.getcwd())).resolve()
BOTS_DIR = BASE_DIR / "hosted_bots"  # المجلد الذي ستحفظ فيه البوتات
METADATA_FILE = BOTS_DIR / "metadata.json"

BOTS_DIR.mkdir(parents=True, exist_ok=True)

def _load_metadata():
    try:
        if METADATA_FILE.exists():
            return json.loads(METADATA_FILE.read_text(encoding='utf-8'))
    except Exception:
        logging.exception("Failed to load metadata")
    return {"bots": {}}

def _save_metadata(meta: dict):
    try:
        METADATA_FILE.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception:
        logging.exception("Failed to save metadata")

# قاموس لتخزين العمليات المشغلة (Process ID: Process Object)
running_bots = {}

# --- الوظائف المساعدة ---

def start_bot_process(file_path, bot_name):
    """تشغيل ملف البوت كعملية فرعية والتقاط الأخطاء"""
    try:
        process = subprocess.Popen(
            [sys.executable, str(file_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        running_bots[bot_name] = {
            "process": process,
            "path": str(file_path),
            "pid": process.pid,
            "started_at": int(time.time())
        }
        # سجل في الميتاداتا
        meta = _load_metadata()
        meta["bots"][bot_name] = meta.get("bots", {}).get(bot_name, {})
        meta["bots"][bot_name].update({"path": str(file_path), "last_started": int(time.time())})
        _save_metadata(meta)
        return True, None
    except Exception as e:
        logging.exception("Failed to start bot process")
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

    # حفظ باسم آمن داخل المجلد (مسار مطلق)
    file_path = BOTS_DIR / Path(doc.file_name).name

    # تحميل الملف
    new_file = await context.bot.get_file(doc.file_id)
    saved = False
    try:
        # محاولة التحميل بالطريقة المتوافقة
        if hasattr(new_file, 'download_to_drive'):
            await new_file.download_to_drive(str(file_path))
        elif hasattr(new_file, 'download'):
            await new_file.download(str(file_path))
        else:
            # حفظ يدوياً من الذاكرة
            bio = await new_file.download_as_bytearray()
            file_path.write_bytes(bio)
        saved = file_path.exists()
    except Exception:
        logging.exception("Failed to download file")
        saved = file_path.exists()

    if not saved:
        await update.message.reply_text(f"❌ فشل حفظ الملف {doc.file_name} على الخادم.")
        return

    # حدّث الميتاداتا
    meta = _load_metadata()
    meta.setdefault("bots", {})
    meta["bots"][doc.file_name] = {
        "path": str(file_path),
        "uploaded_by": update.effective_user.id,
        "uploaded_at": int(time.time())
    }
    _save_metadata(meta)

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
    # أزرار إدارة لكل بوت
    for bot_name in running_bots.keys():
        safe = urllib.parse.quote_plus(bot_name)
        keyboard.append([
            InlineKeyboardButton(f"⏯ تشغيل {bot_name}", callback_data=f"run_{safe}"),
            InlineKeyboardButton(f"🛑 إيقاف {bot_name}", callback_data=f"stop_{safe}"),
            InlineKeyboardButton(f"🗑 حذف {bot_name}", callback_data=f"delete_{safe}")
        ])

    # إضافة زر للمعلومات
    keyboard.append([InlineKeyboardButton("ℹ️ معلومات البوت", callback_data="info")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🖥 لوحة التحكم بالبوتات المشغلة:", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    meta = _load_metadata()

    if data == 'info':
        await query.edit_message_text(f"🔖 إصدار البوت: {VERSION}\n👤 المالك: @ahmaddragon\n📦 عدد البوتات المحفوظة: {len(meta.get('bots', {}))}")
        return

    # فك ترميز الاسم
    if '_' in data:
        cmd, raw = data.split('_', 1)
        bot_name = urllib.parse.unquote_plus(raw)
    else:
        await query.edit_message_text("⚠️ أمر غير معروف.")
        return

    if cmd == 'stop':
        if bot_name in running_bots:
            process = running_bots[bot_name]["process"]
            process.terminate()
            del running_bots[bot_name]
            await query.edit_message_text(f"⛔ تم إيقاف البوت: {bot_name}")
        else:
            await query.edit_message_text("⚠️ البوت متوقف بالفعل أو غير موجود.")
    elif cmd == 'run':
        # شغّل البوت المخزن
        if bot_name in meta.get('bots', {}):
            path = Path(meta['bots'][bot_name]['path'])
            if path.exists():
                success, error = start_bot_process(path, bot_name)
                if success:
                    await query.edit_message_text(f"▶️ تم تشغيل {bot_name}.")
                else:
                    await query.edit_message_text(f"❌ فشل تشغيل: {error}")
            else:
                await query.edit_message_text("❌ ملف البوت غير موجود على الخادم.")
        else:
            await query.edit_message_text("⚠️ لا توجد ميتاداتا لهذا البوت.")
    elif cmd == 'delete':
        # حذف الملف والميتا
        if bot_name in meta.get('bots', {}):
            path = Path(meta['bots'][bot_name]['path'])
            try:
                if path.exists():
                    path.unlink()
                del meta['bots'][bot_name]
                _save_metadata(meta)
                await query.edit_message_text(f"🗑 تم حذف {bot_name}")
            except Exception:
                logging.exception("Failed to delete bot file")
                await query.edit_message_text("❌ فشل الحذف.")
        else:
            await query.edit_message_text("⚠️ لا توجد ميتاداتا لهذا البوت.")
    else:
        await query.edit_message_text("⚠️ أمر غير معروف.")

async def check_errors(context: ContextTypes.DEFAULT_TYPE):
    """وظيفة دورية للتحقق من الأخطاء في البوتات المشغلة"""
    for bot_name, data in list(running_bots.items()):
        process = data["process"]
        # التحقق إذا توقفت العملية فجأة
        poll = process.poll()
        if poll is not None:
            # العملية توقفت، قراءة الخطأ
            _, stderr = process.communicate()
            try:
                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=f"🚨 البوت `{bot_name}` توقف عن العمل!\n\n**الخطأ:**\n`{stderr}`",
                    parse_mode='Markdown'
                )
            except Exception:
                logging.exception("Failed to notify admin")
            del running_bots[bot_name]
            # حدّث الميتاداتا لوسم التوقف
            meta = _load_metadata()
            if bot_name in meta.get('bots', {}):
                meta['bots'][bot_name]['last_exit'] = int(time.time())
                _save_metadata(meta)

def main():
    async def _periodic_check(app: Application):
        await asyncio.sleep(10)
        class _SimpleContext:
            def __init__(self, bot):
                self.bot = bot

        while True:
            try:
                await check_errors(_SimpleContext(app.bot))
            except Exception:
                logging.exception("Error in periodic_check")
            await asyncio.sleep(30)

    async def _on_startup(app: Application):
        # إذا كانت JobQueue متاحة نستخدمها، وإلا ننشئ مهمة دورية بعد بدء التطبيق
        if app.job_queue is not None:
            app.job_queue.run_repeating(check_errors, interval=30, first=10)
        else:
            app.create_task(_periodic_check(app))

    application = Application.builder().token(BOT_TOKEN).post_init(_on_startup).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("dashboard", dashboard))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(CallbackQueryHandler(button_handler))

    print("Main Hosting Bot is running...")
    application.run_polling()

if __name__ == '__main__':
    main()