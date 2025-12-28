import json
import logging
from pathlib import Path
from .config import METADATA_FILE, ADMIN_ID
import time


def _load_metadata():
    try:
        if METADATA_FILE.exists():
            content = METADATA_FILE.read_text(encoding='utf-8')
            if not content.strip():
                return {"bots": {}}
            data = json.loads(content)
            if 'bots' not in data:
                data['bots'] = {}
            return data
    except json.JSONDecodeError:
        logging.error("Metadata file is corrupted. Resetting.")
        return {"bots": {}}
    except Exception:
        logging.exception("Failed to load metadata")
    data = {"bots": {}, "admins": [], "subscriptions": {}, "allowed": {}}
    try:
        if METADATA_FILE.exists():
            content = METADATA_FILE.read_text(encoding='utf-8')
            if not content.strip():
                return data
            loaded = json.loads(content)
            if 'bots' not in loaded:
                loaded['bots'] = {}
            if 'admins' not in loaded:
                loaded['admins'] = []
            if 'subscriptions' not in loaded:
                loaded['subscriptions'] = {}
            if 'allowed' not in loaded:
                loaded['allowed'] = {}
            return loaded
    except json.JSONDecodeError:
        logging.error("Metadata file is corrupted. Resetting.")
        return data
    except Exception:
        logging.exception("Failed to load metadata")
    return data


def _save_metadata(meta: dict):
    try:
        temp_file = METADATA_FILE.with_suffix('.tmp')
        temp_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
        temp_file.replace(METADATA_FILE)
    except Exception:
        logging.exception("Failed to save metadata")


def get_metadata_admins():
    meta = _load_metadata()
    admins = set(meta.get('admins', []) or [])
    try:
        admins.add(int(ADMIN_ID))
    except Exception:
        pass
    return admins


def is_authorized(user_identifier, username=None) -> bool:
    try:
        meta = _load_metadata()
        try:
            if int(user_identifier) == int(ADMIN_ID):
                return True
        except Exception:
            pass

        for a in meta.get('admins', []) or []:
            if not a:
                continue
            astr = str(a)
            if str(user_identifier) == astr:
                return True
            if username:
                uname = username.lstrip('@').lower()
                if astr.lstrip('@').lower() == uname:
                    return True

        allowed = meta.get('allowed', {}) or {}
        for k in list(allowed.keys()):
            kstr = str(k)
            if str(user_identifier) == kstr:
                return True
            if username and kstr.lstrip('@').lower() == username.lstrip('@').lower():
                return True

    except Exception:
        logging.exception('is_authorized failed')
    return False


def get_user_stars(user_id: int) -> int:
    meta = _load_metadata()
    subs = meta.get('subscriptions', {})
    entry = subs.get(str(user_id), {'stars': 0, 'expiry': 0})
    if entry['expiry'] > time.time():
        return entry['stars']
    return 0


def consume_user_star(user_id: int):
    meta = _load_metadata()
    subs = meta.setdefault('subscriptions', {})
    entry = subs.setdefault(str(user_id), {'stars': 0, 'expiry': 0})
    if entry['stars'] > 0 and entry['expiry'] > time.time():
        entry['stars'] -= 1
        _save_metadata(meta)
        return True
    return False
