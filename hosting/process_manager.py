import subprocess
import sys
import threading
import logging
import time
from pathlib import Path
import psutil
from .config import BOTS_DIR, ADMIN_ID
from .metadata import _load_metadata, _save_metadata

running_bots = {}


def install_requirements(bot_dir: Path) -> (bool, str):
    req = bot_dir / 'requirements.txt'
    log = bot_dir / 'install.log'
    if not req.exists():
        return False, 'requirements.txt not found'
    try:
        cmd = [sys.executable, '-m', 'pip', 'install', '-r', str(req)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        out = proc.stdout + '\n' + proc.stderr
        log.write_text(out, encoding='utf-8')
        return proc.returncode == 0, out
    except Exception as e:
        logging.exception('Failed to install requirements')
        try:
            log.write_text(str(e), encoding='utf-8')
        except Exception:
            pass
        return False, str(e)


def get_system_usage():
    cpu = psutil.cpu_percent(interval=None)
    ram = psutil.virtual_memory().percent
    return cpu, ram


def get_bot_usage(pid):
    try:
        proc = psutil.Process(pid)
        with proc.oneshot():
            cpu = proc.cpu_percent(interval=None)
            ram = proc.memory_percent()
        return cpu, ram
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return 0, 0


def start_bot_process(file_path, bot_name, extra_env: dict = None):
    try:
        file_path = Path(file_path).resolve()
        if not file_path.exists():
            return False, f"File not found: {file_path}"

        if bot_name in running_bots:
            try:
                running_bots[bot_name]["process"].terminate()
                running_bots[bot_name]["process"].wait(timeout=5)
            except Exception:
                pass

        env = dict()
        env.update({})
        env.update(extra_env or {})

        env_vars = env.copy()
        env_vars.update({k: v for k, v in env.items()})

        env_full = dict(**env_vars)
        # Ensure PYTHONPATH includes the bot directory
        env_full["PYTHONPATH"] = f"{file_path.parent}:{env_full.get('PYTHONPATH', '')}"
        storage_dir = file_path.parent / "storage"
        storage_dir.mkdir(parents=True, exist_ok=True)
        env_full["BOT_STORAGE_PATH"] = str(storage_dir)

        error_log_path = file_path.parent / "error.log"
        out_log_path = file_path.parent / "output.log"

        process = subprocess.Popen(
            [sys.executable, "-u", str(file_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env_full,
            cwd=str(file_path.parent)
        )
        running_bots[bot_name] = {
            "process": process,
            "path": str(file_path),
            "pid": process.pid,
            "started_at": int(time.time())
        }

        def _reader(pipe, path):
            try:
                with open(path, 'a', encoding='utf-8') as fh:
                    for line in iter(pipe.readline, ''):
                        fh.write(f"[{int(time.time())}] {line}")
            except Exception:
                logging.exception('Failed to capture process IO')

        t_out = threading.Thread(target=_reader, args=(process.stdout, out_log_path), daemon=True)
        t_err = threading.Thread(target=_reader, args=(process.stderr, error_log_path), daemon=True)
        t_out.start()
        t_err.start()

        meta = _load_metadata()
        meta["bots"].setdefault(bot_name, {})
        meta["bots"][bot_name].update({
            "last_started": int(time.time()),
            "status": "running",
            "main": str(file_path)
        })
        _save_metadata(meta)
        logging.info(f"Started bot: {bot_name} (PID: {process.pid})")
        return True, None
    except Exception as e:
        logging.exception(f"Failed to start bot process: {bot_name}")
        return False, str(e)


async def check_errors(context):
    meta = _load_metadata()
    for bot_name, data in list(running_bots.items()):
        process = data["process"]
        poll = process.poll()
        if poll is not None:
            bot_dir = BOTS_DIR / bot_name
            err_path = bot_dir / 'error.log'
            stderr = ''
            try:
                if err_path.exists():
                    stderr = err_path.read_text(encoding='utf-8')[-4000:]
                owner_id = meta.get('bots', {}).get(bot_name, {}).get('files', [{}])[0].get('uploaded_by')
                if not owner_id:
                    owner_id = ADMIN_ID
                await context.bot.send_message(
                    chat_id=owner_id,
                    text=f"🚨 البوت `{bot_name}` توقف عن العمل!\n\n**الخطأ (آخر جزء):**\n`{stderr}`",
                    parse_mode="Markdown"
                )
            except Exception:
                logging.exception(f"Failed to notify about bot {bot_name} error")
            finally:
                try:
                    if bot_name in running_bots:
                        del running_bots[bot_name]
                except Exception:
                    pass
                if bot_name in meta.get('bots', {}):
                    meta["bots"][bot_name]["last_exit"] = int(time.time())
                    _save_metadata(meta)
