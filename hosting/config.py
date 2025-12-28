import os
from pathlib import Path

VERSION = "2.4"
DEFAULT_ADMIN_ID = 8049455831
DEFAULT_BOT_TOKEN = "8328934625:AAEKHcqH7jbizVE6iByqIOikVpEVmshbwr0"

BOT_TOKEN = os.getenv("BOT_TOKEN", DEFAULT_BOT_TOKEN)
ADMIN_ID = int(os.getenv("ADMIN_ID", DEFAULT_ADMIN_ID))

BASE_DIR = Path(os.getenv("BASE_DIR", os.getcwd())).resolve()
BOTS_DIR = BASE_DIR / "hosted_bots"
METADATA_FILE = BOTS_DIR / "metadata.json"

BOTS_DIR.mkdir(parents=True, exist_ok=True)
