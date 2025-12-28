import logging
import threading
from hosting.config import BOT_TOKEN
from hosting.health import run_health_server
from hosting.handlers import register_handlers
from telegram.ext import Application

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)


def main():
    # Start health check server
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()

    try:
        application = Application.builder().token(BOT_TOKEN).build()
    except AttributeError as e:
        logging.exception("Failed to build Application (likely incompatible python-telegram-bot / Python version)")
        import sys
        sys.exit(
            "Application build failed due to AttributeError. "
            "This often indicates an incompatible combination of Python and python-telegram-bot. "
            "Try running with Python 3.11 or pinning a compatible python-telegram-bot version in requirements.txt (for example 20.5/20.6)."
        )

    # register handlers and get startup hook
    startup_hook = register_handlers(application)
    if startup_hook:
        # schedule startup hook to run when the application is running
        try:
            application.create_task(startup_hook(application))
        except Exception:
            # fallback: if create_task not available, attempt to set via post_init
            try:
                application.post_init(startup_hook)
            except Exception:
                pass

    print("Main Hosting Bot is running...")
    application.run_polling()


if __name__ == "__main__":
    main()

async def get_dashboard_markup(meta_data):
    keyboard = []
    bots = meta_data.get("bots", {})
    if not bots:
        return None

    for bot_name, info in bots.items():
        safe = urllib.parse.quote_plus(bot_name)
        is_running = bot_name in running_bots
        status_icon = "🟢" if is_running else "🔴"
        
        # إضافة معلومات الاستهلاك بجانب اسم البوت إذا كان يعمل
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
    if isinstance(message_object, Update): # Called from callback
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
        # شغّل البوت المخزن باستخدام المسار الرئيسي في الإعدادات
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
        # حذف المجلد والميتا
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
        # عرض قائمة الملفات للبوت
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
                    await query.edit_message_text(f"📄 محتوى `{target_file['filename']}`:\n```python\n{escape_markdown(content, version=2)}\n```", parse_mode="MarkdownV2", reply_markup=reply_markup)
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
                await query.edit_message_text(f"🛠️ أرسل لي الكود الجديد للملف `{target_file['filename']}`\\. سأقوم باستبدال المحتوى بالكامل.", parse_mode="MarkdownV2")
                context.user_data['editing_file'] = target_file['path']
            else:
                await query.edit_message_text("⚠️ الملف غير موجود في الميتاداتا.")
        else:
            await query.edit_message_text("⚠️ لا توجد ميتاداتا لهذا البوت.")
    elif cmd == "errors":
        # عرض محتوى ملف الخطأ للبوت
        bot_dir = BOTS_DIR / bot_name
        err = bot_dir / 'error.log'
        if err.exists():
            txt = err.read_text(encoding='utf-8')
            # trim if too long
            if len(txt) > 3500:
                txt = txt[-3500:]
            await query.edit_message_text(f"📛 سجلات الأخطاء ل{bot_name}:\n```\n{escape_markdown(txt, version=2)}\n```", parse_mode="MarkdownV2")
        else:
            await query.edit_message_text("ℹ️ لا توجد سجلات أخطاء لهذا البوت.")
    elif cmd == "cfg":
        # عرض إعدادات البوت
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

# New handler for editing file content
async def handle_code_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id, getattr(update.effective_user, 'username', None)):
        return

    if 'editing_file' in context.user_data and update.message.text:
        file_path = Path(context.user_data['editing_file'])
        try:
            file_path.write_text(update.message.text, encoding='utf-8')
            await update.message.reply_text(f"✅ تم تحديث الملف `{escape_markdown(file_path.name, version=2)}` بنجاح.", parse_mode="MarkdownV2")
            del context.user_data['editing_file']
            # Attempt to restart the bot if it's currently running and this is its main file
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


async def check_errors(context: ContextTypes.DEFAULT_TYPE):
    """وظيفة دورية للتحقق من الأخطاء في البوتات المشغلة"""
    meta = _load_metadata() # Load metadata here
    for bot_name, data in list(running_bots.items()):
        process = data["process"]
        # التحقق إذا توقفت العملية فجأة
        poll = process.poll()
        if poll is not None:
            # العملية توقفت، نحاول قراءة السجل من ملف error.log
            bot_dir = BOTS_DIR / bot_name
            err_path = bot_dir / 'error.log'
            stderr = ''
            try:
                if err_path.exists():
                    stderr = err_path.read_text(encoding='utf-8')[-4000:]
                
                # إرسال التنبيه إلى مالك البوت، أو إلى الأدمن الافتراضي إذا لم يتم العثور على مالك
                owner_id = ADMIN_ID
                bot_meta = meta["bots"].get(bot_name, {})
                files = bot_meta.get("files", [])
                if files:
                    # Assuming the owner is the uploader of the first file
                    owner_id = files[0].get("uploaded_by", ADMIN_ID)

                await context.bot.send_message(
                    chat_id=owner_id,
                    text=f"🚨 البوت `{bot_name}` توقف عن العمل!\n\n**الخطأ (آخر جزء):**\n`{stderr}`",
                    parse_mode="Markdown"
                )

            except Exception as e:
                logging.exception(f"Failed to notify admin about bot {bot_name} error: {e}")
            finally:
                # أزل البوت من running list ووسم التوقف
                try:
                    if bot_name in running_bots:
                        del running_bots[bot_name]
                except Exception:
                    pass
                # قم بتحديث الميتاداتا بعد إزالة البوت من قائمة التشغيل
                if bot_name in meta.get('bots', {}):
                    meta["bots"][bot_name]["last_exit"] = int(time.time())
                    _save_metadata(meta)

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
    
    # Use JobQueue to schedule the task
    job_queue: JobQueue = context.application.job_queue

    # Define the callback for the scheduled job
    async def scheduled_action(ctx: ContextTypes.DEFAULT_TYPE):
        # reload metadata at execution time
        meta = _load_metadata()
        if action == "start":
            try:
                main_p = Path(meta["bots"][bot_name]["settings"]["main"])
            except Exception:
                files = meta.get("bots", {}).get(bot_name, {}).get("files", [])
                main_p = Path(files[-1]["path"]) if files else None
            if main_p:
                await start_bot_process(main_p, bot_name)
            await ctx.bot.send_message(chat_id=ADMIN_ID, text=f"▶️ تم تشغيل البوت المجدول: {bot_name}")
        elif action == "stop":
            if bot_name in running_bots:
                running_bots[bot_name]["process"].terminate()
                del running_bots[bot_name]
                await ctx.bot.send_message(chat_id=ADMIN_ID, text=f"⛔ تم إيقاف البوت المجدول: {bot_name}")

    # Schedule the job
    if frequency == "daily":
        import datetime as _dt
        job_queue.run_daily(scheduled_action, time=_dt.time(hour=hour, minute=minute), data={"bot_name": bot_name, "action": action})
        await update.message.reply_text(f"✅ تم جدولة {action} للبوت {bot_name} يومياً في {time_str}.")
    else:
        # For 'once', we need to calculate the next run time
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
    # find by id or index
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
        # if removed main, pick last as main
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
    # Notify admin/owner about delivery
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
    # إذا كان ملف نصي نعرضه، وإلا نرسله كملف
    try:
        txt = path.read_text(encoding='utf-8')
        if len(txt) > 3500:
            txt = txt[-3500:]
        await update.message.reply_text(f"📄 محتوى {filename}:\n```\n{escape_markdown(txt, version=2)}\n```", parse_mode="MarkdownV2")
    except Exception:
        await update.message.reply_document(document=path)

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_response(404)
            self.end_headers()

def run_health_server():
    server_address = ("", 8000)
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

    async def restart_all_bots():
        """إعادة تشغيل جميع البوتات التي كانت تعمل عند الإغلاق"""
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
                    logging.info(f"Auto-restarting bot: {bot_name}")
                    start_bot_process(main_path, bot_name)

    async def _on_startup(app: Application):
        # تشغيل البوتات المخزنة
        await restart_all_bots()
        
        # إذا كانت JobQueue متاحة نستخدمها، وإلا ننشئ مهمة دورية بعد بدء التطبيق
        if app.job_queue is not None:
            app.job_queue.run_repeating(check_errors, interval=30, first=10)
        else:
            app.create_task(_periodic_check(app))

    try:
        application = Application.builder().token(BOT_TOKEN).post_init(_on_startup).build()
    except AttributeError:
        logging.exception("Failed to build Application on second attempt (likely incompatible python-telegram-bot / Python version)")
        import sys
        sys.exit(
            "Application build failed due to AttributeError. "
            "This often indicates an incompatible combination of Python and python-telegram-bot. "
            "Try running with Python 3.11 or pinning a compatible python-telegram-bot version in requirements.txt (for example 20.5/20.6)."
        )

    # Add message handler for code editing
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_code_message))

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("dashboard", dashboard))
    application.add_handler(CommandHandler("files", files_command))
    application.add_handler(CommandHandler("config", config_command))
    application.add_handler(CommandHandler("set", set_command))
    application.add_handler(CommandHandler("schedule", schedule_task_command)) # New command
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
    application.add_handler(CallbackQueryHandler(button_handler))

    print("Main Hosting Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    # Import datetime for scheduling
    import datetime
    main()
