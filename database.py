import sqlite3
from config import DB_PATH

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
            start_time TEXT DEFAULT 'N/A',
            pid INTEGER DEFAULT NULL
        )
    ''')
    conn.commit()
    conn.close()

def get_db_connection():
    return sqlite3.connect(DB_PATH)

def add_bot(user_id, display_name, internal_name):
    conn = get_db_connection()
    conn.execute("INSERT INTO user_bots (user_id, bot_display_name, internal_filename) VALUES (?, ?, ?)", 
                (user_id, display_name, internal_name))
    conn.commit()
    conn.close()

def update_bot_status(user_id, bot_name, status, start_time='N/A', pid=None):
    conn = get_db_connection()
    conn.execute("UPDATE user_bots SET status=?, start_time=?, pid=? WHERE user_id=? AND bot_display_name=?", 
                (status, start_time, pid, user_id, bot_name))
    conn.commit()
    conn.close()

def get_user_bots(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT bot_display_name, status FROM user_bots WHERE user_id = ?", (user_id,))
    bots = cursor.fetchall()
    conn.close()
    return bots

def get_bot_info(user_id, bot_name):
    conn = get_db_connection()
    res = conn.execute("SELECT internal_filename, status, start_time, pid FROM user_bots WHERE user_id = ? AND bot_display_name = ?", (user_id, bot_name)).fetchone()
    conn.close()
    return res

def delete_bot(user_id, bot_name):
    conn = get_db_connection()
    conn.execute("DELETE FROM user_bots WHERE user_id=? AND bot_display_name=?", (user_id, bot_name))
    conn.commit()
    conn.close()

def get_all_user_bots_full(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT internal_filename, bot_display_name, pid FROM user_bots WHERE user_id = ?", (user_id,))
    bots = cursor.fetchall()
    conn.close()
    return bots

def clear_user_bots(user_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM user_bots WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def count_user_bots(user_id):
    conn = get_db_connection()
    res = conn.execute("SELECT COUNT(*) FROM user_bots WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return res[0]