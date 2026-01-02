import os

# --- الإعدادات الثابتة ---
API_TOKEN = '8328934625:AAFsvlzSvZXOkIhgoIWsp1hWUEyrfExr24c'
DB_PATH = "hosting_pro.db"
BASE_HOST_DIR = "hosted_bots"

# تهيئة البيئة
if not os.path.exists(BASE_HOST_DIR):
    os.makedirs(BASE_HOST_DIR)