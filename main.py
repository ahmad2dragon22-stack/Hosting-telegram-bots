import os
import signal
import subprocess
import logging
import sys
import asyncio
import json
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import shutil
import uuid
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.helpers import escape_markdown

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

# Ensure bot subfolders may be created later
def _load_metadata():
    try:
        if METADATA_FILE.exists():
            data = json.loads(METADATA_FILE.read_text(encoding='utf-8'))
            # normalize
            if 'bots' not in data:
                data['bots'] = {}
            return data
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

def start_bot_process(file_path, bot_name, extra_env: dict = None):
    """تشغيل ملف البوت كعملية فرعية والتقاط الأخطاء
    يدعم تمرير بيئة إضافية لكل بوت."""
    try:
        env = os.environ.copy()
        if extra_env:
            env.update(extra_env)

        process = subprocess.Popen(
            [sys.executable, str(file_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env
        )
        running_bots[bot_name] = {
            "process": process,
            "path": str(file_path),
            "pid": process.pid,
            "started_at": int(time.time())
        }
        # سجل في الميتاداتا
        meta = _load_metadata()
        meta["bots"].setdefault(bot_name, {})
        meta["bots"][bot_name].update({"last_started": int(time.time())})
        _save_metadata(meta)
        return True, None
    except Exception as e:
        logging.exception("Failed to start bot process")
        return False, str(e)

# --- أوامر البوت الرئيسي ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    
    keyboard = [
        [InlineKeyboardButton("🖥 لوحة التحكم", callback_data="dashboard_btn")],
        [InlineKeyboardButton("⬆️ رفع بوت جديد", callback_data="upload_bot_btn")],
        [InlineKeyboardButton("ℹ️ معلومات", callback_data="info_btn") ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "👋 أهلاً بك في مدير استضافة البوتات.\n\n"
        "أنا هنا لمساعدتك في استضافة وإدارة بوتات Telegram الخاصة بك بسهولة.\n\n"
        "اختر أحد الخيارات أدناه للبدء:",
        reply_markup=reply_markup
    )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    doc = update.message.document
    if not doc.file_name.endswith(".py"):
        await update.message.reply_text("❌ يرجى رفع ملفات Python فقط (.py)")
        return

    # اسم البوت يمكن تمريره في caption بصيغة: bot:اسم_البوت
    bot_name = None
    if update.message.caption:
        cap = update.message.caption.strip()
        if cap.lower().startswith('bot:'):
            bot_name = cap.split(':', 1)[1].strip()

    # إن لم يحدده المستخدم، استخدم اسم الملف (بدون امتداد)
    if not bot_name:
        bot_name = Path(doc.file_name).stem

    # مجلد لكل بوت
    bot_dir = BOTS_DIR / bot_name
    bot_dir.mkdir(parents=True, exist_ok=True)

    # حفظ الملف داخل مجلد البوت مع إرفاق uuid كنسخة
    version_id = uuid.uuid4().hex[:8]
    safe_name = f"{version_id}_{Path(doc.file_name).name}"
    file_path = bot_dir / safe_name

    # تحميل الملف
    new_file = await context.bot.get_file(doc.file_id)
    saved = False
    try:
        if hasattr(new_file, 'download_to_drive'):
            await new_file.download_to_drive(str(file_path))
        elif hasattr(new_file, 'download'):
            await new_file.download(str(file_path))
        else:
            bio = await new_file.download_as_bytearray()
            file_path.write_bytes(bio)
        saved = file_path.exists()
    except Exception:
        logging.exception("Failed to download file")
        saved = file_path.exists()

    if not saved:
        await update.message.reply_text(f"❌ فشل حفظ الملف {doc.file_name} على الخادم.")
        return

    # حدّث الميتاداتا لدعم ملفات متعددة
    meta = _load_metadata()
    meta.setdefault('bots', {})
    bot_meta = meta['bots'].setdefault(bot_name, {})
    files = bot_meta.setdefault('files', [])
    files.append({
        'id': version_id,
        'filename': doc.file_name,
        'path': str(file_path),
        'uploaded_by': update.effective_user.id,
        'uploaded_at': int(time.time())
    })
    # إعدادات افتراضية لكل بوت
    bot_meta.setdefault('settings', {
        'enabled': True,
        'auto_restart': True,
        'main': files[-1]['path']
    })
    _save_metadata(meta)

    safe_file_name = escape_markdown(doc.file_name, version=2)
    safe_bot_name = escape_markdown(bot_name, version=2)
    safe_version_id = escape_markdown(version_id, version=2)

    await update.message.reply_text(
        f"📥 تم استلام {safe_file_name} للبوت `{safe_bot_name}` (id={safe_version_id}). جاري التشغيل...", 
        parse_mode='MarkdownV2'
    )

    success, error = start_bot_process(file_path, bot_name)

    if success:
        await update.message.reply_text(f"✅ تم تشغيل `{safe_bot_name}` باستخدام الملف `{safe_file_name}`")
    else:
        safe_error = escape_markdown(error, version=2)
        await update.message.reply_text(f"❌ فشل التشغيل:\n`{safe_error}`", parse_mode='MarkdownV2')

async def get_dashboard_markup(meta_data):
    keyboard = []
    bots = meta_data.get('bots', {})
    if not bots:
        return None

    for bot_name, info in bots.items():
        safe = urllib.parse.quote_plus(bot_name)
        keyboard.append([
            InlineKeyboardButton(f"▶ تشغيل", callback_data=f"run_{safe}"),
            InlineKeyboardButton(f"⏸ إيقاف", callback_data=f"stop_{safe}"),
            InlineKeyboardButton(f"📁 ملفات", callback_data=f"files_{safe}"),
            InlineKeyboardButton(f"⚙️ إعدادات", callback_data=f"cfg_{safe}"),
            InlineKeyboardButton(f"🗑 حذف", callback_data=f"delete_{safe}")
        ])
    keyboard.append([InlineKeyboardButton("ℹ️ معلومات البوت", callback_data="info")])
    return InlineKeyboardMarkup(keyboard)

async def send_dashboard(message_object, context: ContextTypes.DEFAULT_TYPE):
    meta = _load_metadata()
    bots = meta.get("bots", {})

    if not bots:
        await message_object.reply_text("📭 لا توجد بوتات محفوظة حالياً.")
        return

    reply_markup = await get_dashboard_markup(meta)
    await message_object.reply_text("🖥 لوحة التحكم بالبوتات:", reply_markup=reply_markup)

async def dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    await send_dashboard(update.message, context)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    meta = _load_metadata()

    if data == 'info_btn':
        await query.edit_message_text(f"🔖 إصدار البوت: {VERSION}\n👤 المالك: @ahmaddragon\n📦 عدد البوتات المحفوظة: {len(meta.get('bots', {}))}")
        return
    elif data == 'dashboard_btn':
        await send_dashboard(query.message, context) 
        return
    elif data == 'upload_bot_btn':
        await query.edit_message_text("الرجاء رفع ملف Python (بصيغة .py) لتشغيله.")
        return

    if data == 'info': # Old info button, keeping for compatibility if needed elsewhere
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
        # شغّل البوت المخزن باستخدام المسار الرئيسي في الإعدادات
        if bot_name in meta.get('bots', {}):
            bot_meta = meta['bots'][bot_name]
            main_path = None
            if bot_meta.get('settings') and bot_meta['settings'].get('main'):
                main_path = Path(bot_meta['settings']['main'])
            else:
                files = bot_meta.get('files', [])
                if files:
                    main_path = Path(files[-1]['path'])

            if main_path and main_path.exists():
                success, error = start_bot_process(main_path, bot_name)
                if success:
                    await query.edit_message_text(f"▶️ تم تشغيل {bot_name}.")
                else:
                    await query.edit_message_text(f"❌ فشل تشغيل: {error}")
            else:
                await query.edit_message_text("❌ ملف البوت غير موجود على الخادم.")
        else:
            await query.edit_message_text("⚠️ لا توجد ميتاداتا لهذا البوت.")
    elif cmd == 'delete':
        # حذف المجلد والميتا
        if bot_name in meta.get('bots', {}):
            try:
                bot_dir = BOTS_DIR / bot_name
                if bot_dir.exists() and bot_dir.is_dir():
                    shutil.rmtree(bot_dir)
                del meta['bots'][bot_name]
                _save_metadata(meta)
                await query.edit_message_text(f"🗑 تم حذف {bot_name} وجميع ملفاته")
            except Exception:
                logging.exception("Failed to delete bot folder")
                await query.edit_message_text("❌ فشل الحذف.")
        else:
            await query.edit_message_text("⚠️ لا توجد ميتاداتا لهذا البوت.")
    return


async def files_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if not args:
        await update.message.reply_text("❗ استخدم: /files <bot_name>")
        return
    bot_name = args[0]
    meta = _load_metadata()
    if bot_name not in meta.get('bots', {}):
        await update.message.reply_text("⚠️ لا توجد ميتاداتا لهذا البوت.")
        return
    bot_meta = meta['bots'][bot_name]
    files = bot_meta.get('files', [])
    if not files:
        await update.message.reply_text("📭 لا توجد ملفات لهذا البوت.")
        return
    text = "📁 ملفات البوت:\n"
    for i, f in enumerate(files, 1):
        text += f"{i}. {f.get('filename')} (id: {f.get('id')})\n"
    await update.message.reply_text(text)


async def config_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if not args:
        await update.message.reply_text("❗ استخدم: /config <bot_name>")
        return
    bot_name = args[0]
    meta = _load_metadata()
    if bot_name not in meta.get('bots', {}):
        await update.message.reply_text("⚠️ لا توجد ميتاداتا لهذا البوت.")
        return
    bot_meta = meta['bots'][bot_name]
    settings = bot_meta.get('settings', {})
    await update.message.reply_text("⚙️ إعدادات:\n" + json.dumps(settings, ensure_ascii=False, indent=2))


async def set_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if len(args) < 3:
        await update.message.reply_text("❗ استخدم: /set <bot_name> <key> <value>")
        return
    bot_name, key = args[0], args[1]
    value = " ".join(args[2:])
    meta = _load_metadata()
    if bot_name not in meta.get('bots', {}):
        await update.message.reply_text("⚠️ لا توجد ميتاداتا لهذا البوت.")
        return
    bot_meta = meta['bots'][bot_name]
    settings = bot_meta.setdefault('settings', {})
    if value.lower() in ('true', 'false'):
        val = value.lower() == 'true'
    else:
        try:
            val = int(value)
        except Exception:
            val = value
    settings[key] = val
    _save_metadata(meta)
    await update.message.reply_text(f"✅ تم تعيين `{key}` = `{val}` للبوت `{bot_name}`", parse_mode='Markdown')


async def startbot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if not args:
        await update.message.reply_text("❗ استخدم: /startbot <bot_name>")
        return
    bot_name = args[0]
    meta = _load_metadata()
    if bot_name not in meta.get('bots', {}):
        await update.message.reply_text("⚠️ لا توجد ميتاداتا لهذا البوت.")
        return
    bot_meta = meta['bots'][bot_name]
    main_path = None
    if bot_meta.get('settings') and bot_meta['settings'].get('main'):
        main_path = Path(bot_meta['settings']['main'])
    else:
        files = bot_meta.get('files', [])
        if files:
            main_path = Path(files[-1]['path'])

    if main_path and main_path.exists():
        success, error = start_bot_process(main_path, bot_name)
        if success:
            await update.message.reply_text(f"▶️ تم تشغيل {bot_name}.")
        else:
            await update.message.reply_text(f"❌ فشل تشغيل: {error}")
    else:
        await update.message.reply_text("❌ ملف البوت غير موجود على الخادم.")


async def stopbot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if not args:
        await update.message.reply_text("❗ استخدم: /stopbot <bot_name>")
        return
    bot_name = args[0]
    if bot_name in running_bots:
        try:
            running_bots[bot_name]['process'].terminate()
            del running_bots[bot_name]
            await update.message.reply_text(f"⛔ تم إيقاف {bot_name}.")
        except Exception:
            logging.exception("Failed to stop bot")
            await update.message.reply_text("❌ فشل الإيقاف.")
    else:
        await update.message.reply_text("⚠️ البوت غير مشغّل.")


async def restartbot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if not args:
        await update.message.reply_text("❗ استخدم: /restartbot <bot_name>")
        return
    bot_name = args[0]
    await stopbot_command(update, context)
    await startbot_command(update, context)


async def removefile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("❗ استخدم: /removefile <bot_name> <file_id_or_index>")
        return
    bot_name = args[0]
    fid = args[1]
    meta = _load_metadata()
    if bot_name not in meta.get('bots', {}):
        await update.message.reply_text("⚠️ لا توجد ميتاداتا لهذا البوت.")
        return
    bot_meta = meta['bots'][bot_name]
    files = bot_meta.get('files', [])
    target = None
    # find by id or index
    for i, f in enumerate(files):
        if f['id'] == fid or str(i+1) == fid:
            target = f
            idx = i
            break
    if not target:
        await update.message.reply_text("⚠️ لم أجد الملف المطلوب.")
        return
    try:
        p = Path(target['path'])
        if p.exists():
            p.unlink()
        files.pop(idx)
        # if removed main, pick last as main
        settings = bot_meta.setdefault('settings', {})
        if settings.get('main') == str(p):
            settings['main'] = files[-1]['path'] if files else None
        _save_metadata(meta)
        await update.message.reply_text(f"🗑 تم حذف الملف {target['filename']}")
    except Exception:
        logging.exception("Failed to remove file")
        await update.message.reply_text("❌ فشل حذف الملف.")

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_response(404)
            self.end_headers()

def run_health_server():
    server_address = ('', 8000)
    httpd = HTTPServer(server_address, HealthCheckHandler)
    print("Health check server running on port 8000...")
    httpd.serve_forever()

def main():
    # Start health check server in a separate thread
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()

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
    application.add_handler(CommandHandler("files", files_command))
    application.add_handler(CommandHandler("config", config_command))
    application.add_handler(CommandHandler("set", set_command))
    application.add_handler(CommandHandler("startbot", startbot_command))
    application.add_handler(CommandHandler("stopbot", stopbot_command))
    application.add_handler(CommandHandler("restartbot", restartbot_command))
    application.add_handler(CommandHandler("removefile", removefile_command))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(CallbackQueryHandler(button_handler))

    print("Main Hosting Bot is running...")
    application.run_polling()

if __name__ == '__main__':
    main()
