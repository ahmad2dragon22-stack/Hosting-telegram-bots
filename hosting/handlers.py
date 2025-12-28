import json
import logging
import time
import urllib.parse
import shutil
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, JobQueue
from telegram.helpers import escape_markdown

from .config import BOTS_DIR, ADMIN_ID, VERSION
from .metadata import _load_metadata, _save_metadata, is_authorized, get_user_stars, consume_user_star
from .process_manager import start_bot_process, install_requirements, running_bots, get_system_usage, get_bot_usage, check_errors
import datetime


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id, getattr(update.effective_user, 'username', None)):
        return

    keyboard = [
        [InlineKeyboardButton("🖥 لوحة التحكم", callback_data="dashboard_btn")],
        [InlineKeyboardButton("⬆️ رفع بوت جديد", callback_data="upload_bot_btn")],
        [InlineKeyboardButton("ℹ️ معلومات", callback_data="info_btn")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "👋 أهلاً بك في مدير استضافة البوتات.",
        reply_markup=reply_markup
    )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id, getattr(update.effective_user, 'username', None)):
        return

    user_id = update.effective_user.id
    meta = _load_metadata()
    bots_count = sum(1 for b_name, b_info in meta.get("bots", {}).items() if b_info.get("files") and b_info["files"][0].get("uploaded_by") == user_id)
    user_stars = get_user_stars(user_id)

    max_bots = 1
    if user_stars > 0:
        max_bots = 5

    if bots_count >= max_bots:
        await update.message.reply_text(f"❌ لقد وصلت إلى الحد الأقصى لعدد البوتات المسموح بها ({max_bots}).")
        return

    doc = update.message.document
    if not (doc.file_name.endswith(".py") or doc.file_name.lower() == "requirements.txt" or doc.file_name.lower().endswith(".txt")):
        await update.message.reply_text("❌ يرجى رفع ملفات Python فقط (.py) أو ملف requirements.txt")
        return

    bot_name = None
    if update.message.caption:
        cap = update.message.caption.strip()
        if cap.lower().startswith("bot:"):
            bot_name = cap.split(":", 1)[1].strip()

    if not bot_name:
        bot_name = Path(doc.file_name).stem

    bot_dir = BOTS_DIR / bot_name
    bot_dir.mkdir(parents=True, exist_ok=True)

    import uuid
    version_id = uuid.uuid4().hex[:8]
    safe_name = f"{version_id}_{Path(doc.file_name).name}"
    file_path = bot_dir / safe_name

    new_file = await context.bot.get_file(doc.file_id)
    saved = False
    try:
        if hasattr(new_file, "download_to_drive"):
            await new_file.download_to_drive(str(file_path))
        elif hasattr(new_file, "download"):
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

    meta.setdefault("bots", {})
    bot_meta = meta["bots"].setdefault(bot_name, {})
    files = bot_meta.setdefault("files", [])
    files.append({
        "id": version_id,
        "filename": doc.file_name,
        "path": str(file_path),
        "uploaded_by": update.effective_user.id,
        "uploaded_at": int(time.time())
    })
    bot_meta.setdefault("settings", {
        "enabled": True,
        "auto_restart": True,
        "main": files[-1]["path"]
    })
    _save_metadata(meta)

    if doc.file_name.lower() == 'requirements.txt':
        await update.message.reply_text("🔧 تم حفظ requirements.txt. جاري تثبيت الحزم...")
        ok, out = install_requirements(bot_dir)
        if ok:
            await update.message.reply_text("✅ تم تثبيت الحزم بنجاح. راجع install.log للمخرجات.")
        else:
            await update.message.reply_text("⚠️ حدث خطأ أثناء التثبيت. راجع install.log للمخرجات.")
        return

    safe_file_name = escape_markdown(doc.file_name, version=2)
    safe_bot_name = escape_markdown(bot_name, version=2)
    safe_version_id = escape_markdown(version_id, version=2)

    await update.message.reply_text(
        f"📥 تم استلام {safe_file_name} للبوت `{safe_bot_name}` (id={safe_version_id}). جاري التشغيل...",
        parse_mode="MarkdownV2"
    )

    success, error = start_bot_process(file_path, bot_name)

    if success:
        await update.message.reply_text(f"✅ تم تشغيل `{safe_bot_name}` باستخدام الملف `{safe_file_name}`", parse_mode="MarkdownV2")
    else:
        safe_error = escape_markdown(error or 'Unknown error', version=2)
        await update.message.reply_text(f"❌ فشل التشغيل:\n`{safe_error}`", parse_mode="MarkdownV2")


async def get_dashboard_markup(meta_data):
    keyboard = []
    bots = meta_data.get("bots", {})
    if not bots:
        return None

    for bot_name, info in bots.items():
        safe = urllib.parse.quote_plus(bot_name)
        is_running = bot_name in running_bots
        status_icon = "🟢" if is_running else "🔴"
        usage_text = ""
        if is_running:
            cpu, ram = get_bot_usage(running_bots[bot_name]["pid"])
            usage_text = f" (CPU: {cpu:.1f}% RAM: {ram:.1f}%)"

        keyboard.append([InlineKeyboardButton(f"{status_icon} {bot_name}{usage_text}", callback_data=f"info_{safe}")])
        keyboard.append([
            InlineKeyboardButton(f"▶", callback_data=f"run_{safe}"),
            InlineKeyboardButton(f"⏸", callback_data=f"stop_{safe}"),
            InlineKeyboardButton(f"📁", callback_data=f"files_{safe}"),
            InlineKeyboardButton(f"⚙️", callback_data=f"cfg_{safe}"),
            InlineKeyboardButton(f"🧾", callback_data=f"errors_{safe}"),
            InlineKeyboardButton(f"🗑", callback_data=f"delete_{safe}")
        ])
    keyboard.append([InlineKeyboardButton("📊 إحصائيات النظام", callback_data="sys_stats")])
    keyboard.append([InlineKeyboardButton("🔄 تحديث اللوحة", callback_data="dashboard_btn")])
    return InlineKeyboardMarkup(keyboard)


async def send_dashboard(message_object, context: ContextTypes.DEFAULT_TYPE):
    meta = _load_metadata()
    bots = meta.get("bots", {})

    cpu, ram = get_system_usage()
    active_count = len(running_bots)
    text = (
        "🖥 *لوحة التحكم الاحترافية*\n\n"
        f"📊 *استهلاك السيرفر:*\n"
        f"  └ CPU: `{cpu}%` | RAM: `{ram}%` \n\n"
        f"🤖 *البوتات:* `{len(bots)}` إجمالي | `🟢 {active_count}` نشط\n"
        "─────────────────"
    )

    reply_markup = await get_dashboard_markup(meta)
    if isinstance(message_object, Update):
        await message_object.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await message_object.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")


async def dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id, getattr(update.effective_user, 'username', None)):
        return
    await send_dashboard(update.message, context)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    meta = _load_metadata()

    if data == "info_btn":
        await query.edit_message_text(f"🔖 إصدار البوت: {VERSION}\n👤 المالك: @ahmaddragon\n📦 عدد البوتات المحفوظة: {len(meta.get('bots', {}))}")
        return
    elif data == "dashboard_btn":
        await send_dashboard(query.message, context)
        return
    elif data == "upload_bot_btn":
        await query.edit_message_text("الرجاء رفع ملف Python (بصيغة .py) لتشغيله.\n\nيمكنك كتابة `bot:اسم_البوت` في وصف الملف لتسميته.")
        return
    elif data == "sys_stats":
        cpu, ram = get_system_usage()
        active_bots = len(running_bots)
        total_bots = len(meta.get("bots", {}))
        await query.edit_message_text(
            "📊 *إحصائيات النظام*\n\n"
            f"  └ CPU: `{cpu:.1f}%`\n"
            f"  └ RAM: `{ram:.1f}%`\n"
            f"  └ البوتات النشطة: `{active_bots}` / `{total_bots}`\n"
            "─────────────────\n"
            "اضغط /dashboard للعودة للوحة التحكم.",
            parse_mode="Markdown"
        )
        return

    # فك ترميز الاسم
    if "_" in data:
        cmd, raw = data.split("_", 1)
        bot_name = urllib.parse.unquote_plus(raw)
    else:
        await query.edit_message_text("⚠️ أمر غير معروف.")
        return

    if cmd == "stop":
        if bot_name in running_bots:
            process = running_bots[bot_name]["process"]
            process.terminate()
            del running_bots[bot_name]
            await query.edit_message_text(f"⛔ تم إيقاف البوت: {bot_name}")
        else:
            await query.edit_message_text("⚠️ البوت متوقف بالفعل أو غير موجود.")
    elif cmd == "run":
        if bot_name in meta.get("bots", {}):
            bot_meta = meta["bots"][bot_name]
            main_path = None
            if bot_meta.get("settings") and bot_meta["settings"].get("main"):
                main_path = Path(bot_meta["settings"]["main"])
            else:
                files = bot_meta.get("files", [])
                if files:
                    main_path = Path(files[-1]["path"])

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
    elif cmd == "delete":
        if bot_name in meta.get("bots", {}):
            try:
                bot_dir = BOTS_DIR / bot_name
                if bot_dir.exists() and bot_dir.is_dir():
                    shutil.rmtree(bot_dir)
                del meta["bots"][bot_name]
                _save_metadata(meta)
                await query.edit_message_text(f"🗑 تم حذف {bot_name} وجميع ملفاته")
            except Exception:
                logging.exception("Failed to delete bot folder")
                await query.edit_message_text("❌ فشل الحذف.")
        else:
            await query.edit_message_text("⚠️ لا توجد ميتاداتا لهذا البوت.")
    elif cmd == "files":
        if bot_name in meta.get('bots', {}):
            bot_meta = meta['bots'][bot_name]
            files = bot_meta.get('files', [])
            if not files:
                await query.edit_message_text('⚠️ لا توجد ملفات لهذا البوت.')
                return
            lines = [f"{i+1}. {f['filename']} (id={f['id']})" for i, f in enumerate(files)]
            keyboard = [[InlineKeyboardButton("عرض ملف", callback_data=f"viewfile_{bot_name}_{f['id']}")] for f in files if f['filename'].endswith('.py') or f['filename'].endswith('.txt')]
            if keyboard:
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text('📄 ملفات البوت:\n' + '\n'.join(lines), reply_markup=reply_markup)
            else:
                await query.edit_message_text('📄 ملفات البوت:\n' + '\n'.join(lines))
        else:
            await query.edit_message_text("⚠️ لا توجد ميتاداتا لهذا البوت.")
    elif cmd == "viewfile":
        _bot_name, file_id = bot_name.split('_', 1)
        if _bot_name in meta.get('bots', {}):
            bot_meta = meta['bots'][_bot_name]
            files = bot_meta.get('files', [])
            target_file = next((f for f in files if f['id'] == file_id), None)
            if target_file:
                file_path = Path(target_file['path'])
                if file_path.exists() and (file_path.name.endswith('.py') or file_path.name.endswith('.txt')):
                    content = file_path.read_text(encoding='utf-8')
                    if len(content) > 3500:
                        content = content[:3500] + "\n... (محتوى طويل جداً تم اقتطاعه)"
                    keyboard = [[InlineKeyboardButton("تعديل الملف", callback_data=f"editfile_{_bot_name}_{file_id}")]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await query.edit_message_text(f"📄 محتوى {target_file['filename']}:\n```python\n{escape_markdown(content, version=2)}\n```", parse_mode="MarkdownV2", reply_markup=reply_markup)
                else:
                    await query.edit_message_text("⚠️ لا يمكن عرض هذا النوع من الملفات أو الملف غير موجود.")
            else:
                await query.edit_message_text("⚠️ الملف غير موجود في الميتاداتا.")
        else:
            await query.edit_message_text("⚠️ لا توجد ميتاداتا لهذا البوت.")
    elif cmd == "editfile":
        _bot_name, file_id = bot_name.split('_', 1)
        if _bot_name in meta.get('bots', {}):
            bot_meta = meta['bots'][_bot_name]
            files = bot_meta.get('files', [])
            target_file = next((f for f in files if f['id'] == file_id), None)
            if target_file:
                await query.edit_message_text(f"🛠️ أرسل لي الكود الجديد للملف `{target_file['filename']}`. سأقوم باستبدال المحتوى بالكامل.", parse_mode="MarkdownV2")
                context.user_data['editing_file'] = target_file['path']
            else:
                await query.edit_message_text("⚠️ الملف غير موجود في الميتاداتا.")
        else:
            await query.edit_message_text("⚠️ لا توجد ميتاداتا لهذا البوت.")
    elif cmd == "errors":
        bot_dir = BOTS_DIR / bot_name
        err = bot_dir / 'error.log'
        if err.exists():
            txt = err.read_text(encoding='utf-8')
            if len(txt) > 3500:
                txt = txt[-3500:]
            await query.edit_message_text(f"📛 سجلات الأخطاء ل{bot_name}:\n```\n{escape_markdown(txt, version=2)}\n```", parse_mode="MarkdownV2")
        else:
            await query.edit_message_text("ℹ️ لا توجد سجلات أخطاء لهذا البوت.")
    elif cmd == "cfg":
        if bot_name in meta.get("bots", {}):
            bot_meta = meta["bots"][bot_name]
            settings = bot_meta.get("settings", {})
            text = json.dumps(settings, ensure_ascii=False, indent=2)
            await query.edit_message_text(f"⚙️ إعدادات `{bot_name}`:\n`{escape_markdown(text, version=2)}`", parse_mode="MarkdownV2")
    elif cmd == "info":
        if bot_name in meta.get("bots", {}):
            info = meta["bots"][bot_name]
            status = "يعمل 🟢" if bot_name in running_bots else "متوقف 🔴"
            last_started = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(info.get('last_started', 0)))
            text = (
                f"ℹ️ معلومات البوت: {bot_name}\n"
                f"📊 الحالة: {status}\n"
                f"📂 عدد الملفات: {len(info.get('files', []))}\n"
                f"⏰ آخر تشغيل: {last_started}\n"
                f"🚀 المسار الرئيسي: `{escape_markdown(info.get('settings', {}).get('main', 'غير محدد'), version=2)}`"
            )
            await query.edit_message_text(text, parse_mode="MarkdownV2")
    else:
        await query.edit_message_text("⚠️ أمر غير معروف.")

    return


async def handle_code_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id, getattr(update.effective_user, 'username', None)):
        return

    if 'editing_file' in context.user_data and update.message and update.message.text:
        file_path = Path(context.user_data['editing_file'])
        try:
            file_path.write_text(update.message.text, encoding='utf-8')
            await update.message.reply_text(f"✅ تم تحديث الملف `{escape_markdown(file_path.name, version=2)}` بنجاح.", parse_mode="MarkdownV2")
            del context.user_data['editing_file']
            for bot_name, bot_info in running_bots.items():
                if Path(bot_info['path']) == file_path:
                    await update.message.reply_text(f"🔄 جاري إعادة تشغيل البوت `{escape_markdown(bot_name, version=2)}` لتطبيق التغييرات...", parse_mode="MarkdownV2")
                    meta = _load_metadata()
                    bot_meta = meta["bots"][bot_name]
                    main_path = Path(bot_meta["settings"]["main"])
                    success, error = start_bot_process(main_path, bot_name)
                    if not success:
                        await update.message.reply_text(f"❌ فشلت إعادة التشغيل: `{escape_markdown(error, version=2)}`", parse_mode="MarkdownV2")
                    break

        except Exception as e:
            await update.message.reply_text(f"❌ فشل حفظ الملف: `{escape_markdown(str(e), version=2)}`", parse_mode="MarkdownV2")
            del context.user_data['editing_file']
        return


async def schedule_task_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id, getattr(update.effective_user, 'username', None)):
        return
    args = context.args
    if len(args) < 3:
        await update.message.reply_text("❗ استخدم: /schedule <bot_name> <start|stop> <HH:MM> [daily|once]")
        return
    
    bot_name = args[0]
    action = args[1].lower()
    time_str = args[2]
    frequency = args[3].lower() if len(args) > 3 else "once"

    if action not in ["start", "stop"]:
        await update.message.reply_text("❗ الإجراء يجب أن يكون 'start' أو 'stop'.")
        return

    try:
        hour, minute = map(int, time_str.split(":"))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("وقت غير صالح")
    except ValueError:
        await update.message.reply_text("❗ صيغة الوقت غير صالحة. استخدم HH:MM.")
        return
    
    job_queue: JobQueue = context.application.job_queue

    async def scheduled_action(ctx: ContextTypes.DEFAULT_TYPE):
        meta = _load_metadata()
        if action == "start":
            try:
                main_p = Path(meta["bots"][bot_name]["settings"]["main"])
            except Exception:
                files = meta.get("bots", {}).get(bot_name, {}).get("files", [])
                main_p = Path(files[-1]["path"]) if files else None
            if main_p:
                start_bot_process(main_p, bot_name)
            await ctx.bot.send_message(chat_id=ADMIN_ID, text=f"▶️ تم تشغيل البوت المجدول: {bot_name}")
        elif action == "stop":
            if bot_name in running_bots:
                running_bots[bot_name]["process"].terminate()
                del running_bots[bot_name]
                await ctx.bot.send_message(chat_id=ADMIN_ID, text=f"⛔ تم إيقاف البوت المجدول: {bot_name}")

    if frequency == "daily":
        job_queue.run_daily(scheduled_action, time=datetime.time(hour=hour, minute=minute), data={"bot_name": bot_name, "action": action})
        await update.message.reply_text(f"✅ تم جدولة {action} للبوت {bot_name} يومياً في {time_str}.")
    else:
        now = datetime.datetime.now()
        target_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target_time < now:
            target_time += datetime.timedelta(days=1)
        job_queue.run_once(scheduled_action, when=target_time, data={"bot_name": bot_name, "action": action})
        await update.message.reply_text(f"✅ تم جدولة {action} للبوت {bot_name} مرة واحدة في {time_str}.")


async def files_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id, getattr(update.effective_user, 'username', None)):
        return
    args = context.args
    if not args:
        await update.message.reply_text("❗ استخدم: /files <bot_name>")
        return
    bot_name = args[0]
    meta = _load_metadata()
    if bot_name not in meta.get("bots", {}):
        await update.message.reply_text("⚠️ لا توجد ميتاداتا لهذا البوت.")
        return
    bot_meta = meta["bots"][bot_name]
    files = bot_meta.get("files", [])
    if not files:
        await update.message.reply_text("📭 لا توجد ملفات لهذا البوت.")
        return
    text = "📁 ملفات البوت:\n"
    for i, f in enumerate(files, 1):
        text += f"{i}. {f.get('filename')} (id: {f.get('id')})\n"
    await update.message.reply_text(text)


async def config_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id, getattr(update.effective_user, 'username', None)):
        return
    args = context.args
    if not args:
        await update.message.reply_text("❗ استخدم: /config <bot_name>")
        return
    bot_name = args[0]
    meta = _load_metadata()
    if bot_name not in meta.get("bots", {}):
        await update.message.reply_text("⚠️ لا توجد ميتاداتا لهذا البوت.")
        return
    bot_meta = meta["bots"][bot_name]
    settings = bot_meta.get("settings", {})
    await update.message.reply_text("⚙️ إعدادات:\n" + json.dumps(settings, ensure_ascii=False, indent=2))


async def set_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id, getattr(update.effective_user, 'username', None)):
        return
    args = context.args
    if len(args) < 3:
        await update.message.reply_text("❗ استخدم: /set <bot_name> <key> <value>")
        return
    bot_name, key = args[0], args[1]
    value = " ".join(args[2:])
    meta = _load_metadata()
    if bot_name not in meta.get("bots", {}):
        await update.message.reply_text("⚠️ لا توجد ميتاداتا لهذا البوت.")
        return
    bot_meta = meta["bots"][bot_name]
    settings = bot_meta.setdefault("settings", {})
    if value.lower() in ("true", "false"):
        val = value.lower() == "true"
    else:
        try:
            val = int(value)
        except Exception:
            val = value
    settings[key] = val
    _save_metadata(meta)
    await update.message.reply_text(f"✅ تم تعيين `{key}` = `{val}` للبوت `{bot_name}`", parse_mode="Markdown")


async def startbot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id, getattr(update.effective_user, 'username', None)):
        return
    args = context.args
    if not args:
        await update.message.reply_text("❗ استخدم: /startbot <bot_name>")
        return
    bot_name = args[0]
    meta = _load_metadata()
    if bot_name not in meta.get("bots", {}):
        await update.message.reply_text("⚠️ لا توجد ميتاداتا لهذا البوت.")
        return
    bot_meta = meta["bots"][bot_name]
    main_path = None
    if bot_meta.get("settings") and bot_meta["settings"].get("main"):
        main_path = Path(bot_meta["settings"]["main"])
    else:
        files = bot_meta.get("files", [])
        if files:
            main_path = Path(files[-1]["path"])

    if main_path and main_path.exists():
        success, error = start_bot_process(main_path, bot_name)
        if success:
            await update.message.reply_text(f"▶️ تم تشغيل {bot_name}.")
        else:
            await update.message.reply_text(f"❌ فشل تشغيل: {error}")
    else:
        await update.message.reply_text("❌ ملف البوت غير موجود على الخادم.")


async def stopbot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id, getattr(update.effective_user, 'username', None)):
        return
    args = context.args
    if not args:
        await update.message.reply_text("❗ استخدم: /stopbot <bot_name>")
        return
    bot_name = args[0]
    if bot_name in running_bots:
        try:
            running_bots[bot_name]["process"].terminate()
            del running_bots[bot_name]
            await update.message.reply_text(f"⛔ تم إيقاف {bot_name}.")
        except Exception:
            logging.exception("Failed to stop bot")
            await update.message.reply_text("❌ فشل الإيقاف.")
    else:
        await update.message.reply_text("⚠️ البوت غير مشغّل.")


async def restartbot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id, getattr(update.effective_user, 'username', None)):
        return
    args = context.args
    if not args:
        await update.message.reply_text("❗ استخدم: /restartbot <bot_name>")
        return
    bot_name = args[0]
    await stopbot_command(update, context)
    await startbot_command(update, context)


async def removefile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id, getattr(update.effective_user, 'username', None)):
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("❗ استخدم: /removefile <bot_name> <file_id_or_index>")
        return
    bot_name = args[0]
    fid = args[1]
    meta = _load_metadata()
    if bot_name not in meta.get("bots", {}):
        await update.message.reply_text("⚠️ لا توجد ميتاداتا لهذا البوت.")
        return
    bot_meta = meta["bots"][bot_name]
    files = bot_meta.get("files", [])
    target = None
    for i, f in enumerate(files):
        if f["id"] == fid or str(i+1) == fid:
            target = f
            idx = i
            break
    if not target:
        await update.message.reply_text("⚠️ لم أجد الملف المطلوب.")
        return
    try:
        p = Path(target["path"])
        if p.exists():
            p.unlink()
        files.pop(idx)
        settings = bot_meta.setdefault("settings", {})
        if settings.get("main") == str(p):
            settings["main"] = files[-1]["path"] if files else None
        _save_metadata(meta)
        await update.message.reply_text(f"🗑 تم حذف الملف {target['filename']}")
    except Exception:
        logging.exception("Failed to remove file")
        await update.message.reply_text("❌ فشل حذف الملف.")


async def allow_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id, getattr(update.effective_user, 'username', None)):
        return
    args = context.args
    if not args:
        await update.message.reply_text("❗ استخدم: /allow <user_id>")
        return
    uid = str(args[0])
    meta = _load_metadata()
    allowed = meta.setdefault('allowed', {})
    allowed[uid] = True
    _save_metadata(meta)
    await update.message.reply_text(f"✅ تم السماح للمستخدم: {uid}")


async def revoke_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id, getattr(update.effective_user, 'username', None)):
        return
    args = context.args
    if not args:
        await update.message.reply_text("❗ استخدم: /revoke <user_id>")
        return
    uid = str(args[0])
    meta = _load_metadata()
    allowed = meta.setdefault('allowed', {})
    if uid in allowed:
        del allowed[uid]
        _save_metadata(meta)
        await update.message.reply_text(f"🗑 تم سحب الصلاحية من: {uid}")
    else:
        await update.message.reply_text("⚠️ المستخدم غير موجود في قائمة المسموحين.")


async def grant_stars_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    args = context.args
    if len(args) < 3:
        await update.message.reply_text("❗ استخدم: /grant_stars <user_id> <count> <days>")
        return
    uid = str(args[0])
    try:
        count = int(args[1])
        days = int(args[2])
    except Exception:
        await update.message.reply_text("❗ تأكد من صحة القيم (عدد النجوم وعدد الأيام)")
        return
    meta = _load_metadata()
    subs = meta.setdefault('subscriptions', {})
    entry = subs.setdefault(uid, {'stars': 0, 'expiry': 0})
    entry['stars'] = entry.get('stars', 0) + count
    expiry = max(int(time.time()), entry.get('expiry', 0)) + days * 24 * 3600
    entry['expiry'] = expiry
    _save_metadata(meta)
    await update.message.reply_text(f"⭐ تم إضافة {count} نجوم للمستخدم {uid} لمدة {days} يوم.")
    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=f"تم توصيل {count} نجوم إلى {uid} من قبل {update.effective_user.id}")
    except Exception:
        pass


async def get_errors_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    args = context.args
    if not args:
        await update.message.reply_text("❗ استخدم: /get_errors <bot_name>")
        return
    bot_name = args[0]
    bot_dir = BOTS_DIR / bot_name
    err = bot_dir / 'error.log'
    if not err.exists():
        await update.message.reply_text("ℹ️ لا توجد سجلات أخطاء لهذا البوت.")
        return
    txt = err.read_text(encoding='utf-8')
    if len(txt) > 3500:
        txt = txt[-3500:]
    await update.message.reply_text(f"📛 سجلات الأخطاء ل{bot_name}:\n```\n{escape_markdown(txt, version=2)}\n```", parse_mode="MarkdownV2")


async def storage_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    args = context.args
    if not args:
        await update.message.reply_text("❗ استخدم: /storage_list <bot_name>")
        return
    bot_name = args[0]
    bot_dir = BOTS_DIR / bot_name / 'storage'
    if not bot_dir.exists():
        await update.message.reply_text("ℹ️ لا توجد ملفات تخزين لهذا البوت.")
        return
    files = [p.name for p in bot_dir.iterdir() if p.is_file()]
    if not files:
        await update.message.reply_text("ℹ️ لا توجد ملفات تخزين لهذا البوت.")
        return
    await update.message.reply_text("📦 ملفات التخزين:\n" + "\n".join(files))


async def storage_get_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("❗ استخدم: /storage_get <bot_name> <filename>")
        return
    bot_name = args[0]
    filename = args[1]
    path = BOTS_DIR / bot_name / 'storage' / filename
    if not path.exists():
        await update.message.reply_text("⚠️ الملف غير موجود.")
        return
    try:
        txt = path.read_text(encoding='utf-8')
        if len(txt) > 3500:
            txt = txt[-3500:]
        await update.message.reply_text(f"📄 محتوى {filename}:\n```\n{escape_markdown(txt, version=2)}\n```", parse_mode="MarkdownV2")
    except Exception:
        await update.message.reply_document(document=path)


def register_handlers(application):
    from telegram.ext import CommandHandler, MessageHandler, filters, CallbackQueryHandler
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("dashboard", dashboard))
    application.add_handler(CommandHandler("files", files_command))
    application.add_handler(CommandHandler("config", config_command))
    application.add_handler(CommandHandler("set", set_command))
    application.add_handler(CommandHandler("schedule", schedule_task_command))
    application.add_handler(CommandHandler("startbot", startbot_command))
    application.add_handler(CommandHandler("stopbot", stopbot_command))
    application.add_handler(CommandHandler("restartbot", restartbot_command))
    application.add_handler(CommandHandler("removefile", removefile_command))
    application.add_handler(CommandHandler("allow", allow_command))
    application.add_handler(CommandHandler("revoke", revoke_command))
    application.add_handler(CommandHandler("grant_stars", grant_stars_command))
    application.add_handler(CommandHandler("get_errors", get_errors_command))
    application.add_handler(CommandHandler("storage_list", storage_list_command))
    application.add_handler(CommandHandler("storage_get", storage_get_command))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_code_message))
    application.add_handler(CallbackQueryHandler(button_handler))

    async def _on_startup(app):
        # restart bots
        meta = _load_metadata()
        bots = meta.get("bots", {})
        for bot_name, bot_meta in bots.items():
            settings = bot_meta.get("settings", {})
            if settings.get("enabled", True) and settings.get("auto_restart", True):
                main_path = settings.get("main")
                if not main_path:
                    files = bot_meta.get("files", [])
                    if files:
                        main_path = files[-1]["path"]
                if main_path and Path(main_path).exists():
                    start_bot_process(main_path, bot_name)

        if app.job_queue is not None:
            app.job_queue.run_repeating(check_errors, interval=30, first=10)

    return _on_startup
