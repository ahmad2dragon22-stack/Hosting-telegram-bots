from telebot import types
import database

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
    bots = database.get_user_bots(user_id)

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