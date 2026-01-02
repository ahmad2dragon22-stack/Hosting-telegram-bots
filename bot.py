import telebot
from config import API_TOKEN
import database
import handlers

def main():
    # تهيئة قاعدة البيانات
    database.init_db()
    
    # إنشاء كائن البوت
    bot = telebot.TeleBot(API_TOKEN)
    
    # تسجيل المعالجات
    handlers.register_handlers(bot)
    
    print("✅ System Online: Smart Host Pro is running...")
    bot.infinity_polling()

if __name__ == "__main__":
    main()