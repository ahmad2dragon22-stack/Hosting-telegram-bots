import os
import subprocess
import signal
import psutil
from datetime import datetime
from config import BASE_HOST_DIR
import database

# قاموس لتتبع العمليات المشغلة خلال الجلسة الحالية (كاحتياطي)
running_processes = {}

def is_process_running(pid):
    if pid is None:
        return False
    try:
        process = psutil.Process(pid)
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False

def start_bot(user_id, bot_name):
    bot_info = database.get_bot_info(user_id, bot_name)
    if not bot_info:
        return False, "لم يتم العثور على البوت"
    
    internal_name, status, _, pid = bot_info
    
    # تحقق إذا كان يعمل بالفعل (عبر الـ PID المخزن)
    if is_process_running(pid):
        database.update_bot_status(user_id, bot_name, 'running', datetime.now().strftime("%Y-%m-%d %H:%M"), pid)
        return False, "البوت يعمل بالفعل!"

    file_path = os.path.join(BASE_HOST_DIR, internal_name)
    if not os.path.exists(file_path):
        return False, "ملف البوت غير موجود"

    try:
        # تشغيل البوت في عملية مستقلة تماماً (Detached)
        # نستخدم python3 لضمان التوافق مع أغلب الاستضافات
        process = subprocess.Popen(
            ['python3', file_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        
        proc_key = f"{user_id}_{bot_name}"
        running_processes[proc_key] = process
        
        start_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        database.update_bot_status(user_id, bot_name, 'running', start_time, process.pid)
        return True, "🚀 انطلق البوت بنجاح!"
    except Exception as e:
        return False, f"فشل التشغيل: {e}"

def stop_bot(user_id, bot_name):
    bot_info = database.get_bot_info(user_id, bot_name)
    if not bot_info:
        return False, "لم يتم العثور على البوت"
    
    internal_name, status, _, pid = bot_info
    proc_key = f"{user_id}_{bot_name}"

    # محاولة الإيقاف عبر القاموس أولاً
    if proc_key in running_processes:
        try:
            running_processes[proc_key].terminate()
            del running_processes[proc_key]
        except:
            pass
    
    # محاولة الإيقاف عبر الـ PID (لضمان القتل حتى لو أعيد تشغيل البوت الأساسي)
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except Exception as e:
            print(f"Error killing process {pid}: {e}")

    database.update_bot_status(user_id, bot_name, 'stopped', 'N/A', None)
    return True, "🛑 تم إيقاف البوت"

def delete_bot_files(user_id, bot_name):
    bot_info = database.get_bot_info(user_id, bot_name)
    if bot_info:
        internal_name = bot_info[0]
        stop_bot(user_id, bot_name)
        file_path = os.path.join(BASE_HOST_DIR, internal_name)
        if os.path.exists(file_path):
            os.remove(file_path)
        database.delete_bot(user_id, bot_name)
        return True
    return False

def wipe_all(user_id):
    bots = database.get_all_user_bots_full(user_id)
    for internal, display, pid in bots:
        stop_bot(user_id, display)
        file_path = os.path.join(BASE_HOST_DIR, internal)
        if os.path.exists(file_path):
            os.remove(file_path)
    database.clear_user_bots(user_id)