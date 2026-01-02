import os
import time
import telebot
from telebot import types
from config import BASE_HOST_DIR
import database
import bot_manager
import markups

def register_handlers(bot):
    
    @bot.message_handler(commands=['start'])
    def start(message):
        welcome_text = (
            f"🤖 **مرحباً بك في نظام الاستضافة الاحترافي**\n\n"
            f"عزيزي {message.from_user.first_name}، يمكنك هنا رفع وإدارة بوتاتك بسهولة.\n"
            "استخدم الأزرار أدناه للبدء."
        )
        bot.send_message(message.chat.id, welcome_text, reply_markup=markups.get_main_menu(), parse_mode="Markdown")

    @bot.callback_query_handler(func=lambda call: True)
    def handle_callbacks(call):
        user_id = call.from_user.id
        data = call.data

        if data == "nav_home":
            bot.edit_message_text("القائمة الرئيسية:", call.message.chat.id, call.message.message_id, reply_markup=markups.get_main_menu())
        
        elif data == "nav_upload":
            msg = bot.send_message(call.message.chat.id, "📥 **من فضلك أرسل ملف البوت الآن (.py):**")
            bot.register_next_step_handler(msg, lambda m: process_file_upload(m, bot))
        
        elif data == "nav_dashboard":
            bot.edit_message_text("💻 **لوحة التحكم ببوتاتك:**\nاضغط على اسم البوت لإدارته.", call.message.chat.id, call.message.message_id, reply_markup=markups.get_dashboard_markup(user_id))

        elif data == "nav_stats":
            count = database.count_user_bots(user_id)
            bot.answer_callback_query(call.id, f"لديك {count} بوتات في نظامنا", show_alert=True)

        elif data == "nav_settings":
            settings_text = "⚙️ **إعدادات الحساب الاستضافي:**\n\nيمكنك من هنا التحكم في تفضيلاتك العامة."
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🗑 مسح كافة البيانات", callback_data="exec:wipe_all"))
            markup.add(types.InlineKeyboardButton("🔙 عودة", callback_data="nav_home"))
            bot.edit_message_text(settings_text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

        elif data.startswith("manage:"):
            bot_name = data.split(":")[1]
            bot_info = database.get_bot_info(user_id, bot_name)
            
            if bot_info:
                internal_name, status, start_time, pid = bot_info
                
                # تحديث الحالة الحقيقية قبل العرض
                is_running = bot_manager.is_process_running(pid)
                current_status = "running" if is_running else "stopped"
                if current_status != status:
                    database.update_bot_status(user_id, bot_name, current_status, start_time if is_running else 'N/A', pid if is_running else None)
                    status = current_status
                    if not is_running: start_time = 'N/A'

                status_text = "🟢 يعمل حالياً" if status == "running" else "🔴 متوقف"
                msg_text = f"🤖 **إدارة البوت:** `{bot_name}`\n\n📊 الحالة: {status_text}\n⏰ وقت البدء: `{start_time}`"
                bot.edit_message_text(msg_text, call.message.chat.id, call.message.message_id, reply_markup=markups.get_manage_markup(bot_name, status), parse_mode="Markdown")

        elif data.startswith("exec:"):
            parts = data.split(":")
            action = parts[1]
            
            if action == "wipe_all":
                bot_manager.wipe_all(user_id)
                bot.answer_callback_query(call.id, "تم مسح كافة البيانات بنجاح")
                bot.edit_message_text("تمت إعادة ضبط حسابك.", call.message.chat.id, call.message.message_id, reply_markup=markups.get_main_menu())
                return

            bot_name = parts[2]
            
            if action == "start":
                success, msg = bot_manager.start_bot(user_id, bot_name)
                bot.answer_callback_query(call.id, msg, show_alert=not success)
            elif action == "stop":
                success, msg = bot_manager.stop_bot(user_id, bot_name)
                bot.answer_callback_query(call.id, msg)
            elif action == "delete":
                bot_manager.delete_bot_files(user_id, bot_name)
                bot.answer_callback_query(call.id, "🗑 تم حذف البوت نهائياً")
                bot.edit_message_text("💻 لوحة التحكم:", call.message.chat.id, call.message.message_id, reply_markup=markups.get_dashboard_markup(user_id))
                return

            # تحديث الواجهة
            new_call = types.CallbackQuery(id=call.id, from_user=call.from_user, chat_instance=call.chat_instance, message=call.message, data=f"manage:{bot_name}")
            handle_callbacks(new_call)

def process_file_upload(message, bot):
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
        
        database.add_bot(user_id, display_name, internal_name)
        
        bot.send_message(message.chat.id, f"✅ تم استلام البوت `{display_name}` بنجاح!\nاذهب للوحة التحكم لتشغيله.", parse_mode="Markdown", reply_markup=markups.get_main_menu())
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ حدث خطأ أثناء الحفظ: {e}")