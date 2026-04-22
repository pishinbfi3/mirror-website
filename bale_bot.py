import os
import time
import json
import math
import shutil
import tempfile
import subprocess
from pathlib import Path
import requests
import sqlite3

TOKEN = os.getenv("BALE_BOT_TOKEN")
BASE_URL = f"https://tapi.bale.ai/bot{TOKEN}"
ADMIN_ID = os.getenv("ADMIN_ID", "")

# WORKDIR باید همان مسیر repo کلون شده باشد
WORKDIR = Path(os.getenv("WORKDIR", "")).resolve()
if not WORKDIR.exists():
    raise RuntimeError("WORKDIR does not exist. Clone the phdler repo and set WORKDIR to its folder.")

# مسیر دانلود از env
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", "/tmp/phdler_downloads")).resolve()
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


# ---------------------------------------------------------
# 1) جلوگیری کامل از EOFError و UnboundLocalError
# ---------------------------------------------------------

def ensure_database_ready():
    db_path = WORKDIR / "database.db"
    if not db_path.exists():
        # اگر دیتابیس وجود ندارد
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS ph_items (id INTEGER PRIMARY KEY, url TEXT, title TEXT, views INTEGER, likes INTEGER, dislikes INTEGER, duration INTEGER, added TEXT, model TEXT, pornstar TEXT, channel TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS ph_videos (id INTEGER PRIMARY KEY, url TEXT, title TEXT, views INTEGER, likes INTEGER, dislikes INTEGER, duration INTEGER, added TEXT, model TEXT, pornstar TEXT, channel TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS ph_models (id INTEGER PRIMARY KEY, name TEXT, url TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS ph_pornstars (id INTEGER PRIMARY KEY, name TEXT, url TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS ph_channels (id INTEGER PRIMARY KEY, name TEXT, url TEXT)")
        conn.commit()
        conn.close()
        run_phdler(["start"])

# ---------------------------------------------------------
# 2) API functions
# ---------------------------------------------------------
def api(method, data=None, files=None, timeout=120):
    url = f"{BASE_URL}/{method}"
    if files:
        return requests.post(url, data=data, files=files, timeout=timeout).json()
    return requests.post(url, data=data, timeout=timeout).json()


def send_message(chat_id, text):
    return api("sendMessage", data={"chat_id": chat_id, "text": text})


def send_document(chat_id, file_path, caption=None):
    file_path = Path(file_path)
    if file_path.stat().st_size <= MAX_FILE_SIZE:
        with open(file_path, "rb") as f:
            return api("sendDocument", data={"chat_id": chat_id, "caption": caption or ""}, files={"document": f})

    # بزرگ‌تر از 10MB → تقسیم فایل
    parts = split_file(file_path, MAX_FILE_SIZE)
    responses = []
    for i, part in enumerate(parts, 1):
        with open(part, "rb") as f:
            resp = api("sendDocument", data={
                "chat_id": chat_id,
                "caption": f"{caption or ''} (part {i}/{len(parts)})"
            }, files={"document": f})
            responses.append(resp)
    return responses


def split_file(file_path, chunk_size=10 * 1024 * 1024):
    file_path = Path(file_path)
    parts_dir = file_path.parent / f"{file_path.stem}_parts"
    parts_dir.mkdir(exist_ok=True)
    parts = []
    with open(file_path, "rb") as f:
        i = 0
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            i += 1
            part_path = parts_dir / f"{file_path.stem}.part{i:03d}"
            with open(part_path, "wb") as pf:
                pf.write(chunk)
            parts.append(part_path)
    return parts


# ---------------------------------------------------------
# 3) اجرای phdler.py
# ---------------------------------------------------------
def run_phdler(args, input_text=None):
    cmd = ["python3", "phdler.py"] + args
    proc = subprocess.run(
        cmd,
        input=input_text,
        capture_output=True,
        text=True,
        cwd=str(WORKDIR)
    )

    output = ""
    if proc.stdout:
        output += proc.stdout
    if proc.stderr:
        output += "\n[stderr]\n" + proc.stderr

    return proc.returncode, output.strip()


def parse_command(text):
    text = text.strip()
    if not text.startswith("/"):
        return None, None
    parts = text.split(maxsplit=1)
    return parts[0].lower(), (parts[1] if len(parts) > 1 else "")


# ---------------------------------------------------------
# 4) Handlers (هر دستور → اول دیتابیس را آماده کن)
# ---------------------------------------------------------
def handle_start(chat_id):
    send_message(chat_id, "سلام! ربات آماده است.\n/help را ببین.")


def handle_help(chat_id):
    send_message(chat_id,
        "/dlstart\n"
        "/custom <url>\n"
        "/add <type> <value>\n"
        "/list <type>\n"
        "/delete <type> <id>"
    )


def handle_dlstart(chat_id):
    ensure_database_ready()
    code, out = run_phdler(["start"])
    send_message(chat_id, f"نتیجه اجرای start:\n\n{out[:3500]}")


def handle_custom(chat_id, arg):
    ensure_database_ready()
    if not arg:
        return send_message(chat_id, "یک URL بده")
    code, out = run_phdler(["custom", arg])
    send_message(chat_id, f"نتیجه custom:\n\n{out[:3500]}")


def handle_add(chat_id, arg):
    ensure_database_ready()
    if not arg:
        return send_message(chat_id, "مثال: /add model <url>")
    parts = arg.split(maxsplit=1)
    type_ = parts[0]
    value = parts[1] if len(parts) > 1 else ""
    code, out = run_phdler(["add", type_], input_text=value)
    send_message(chat_id, f"نتیجه add:\n\n{out[:3500]}")


def handle_list(chat_id, arg):
    ensure_database_ready()
    if not arg:
        return send_message(chat_id, "مثال: /list all")
    code, out = run_phdler(["list", arg])
    send_message(chat_id, f"فهرست:\n\n{out[:3500]}")


def handle_delete(chat_id, arg):
    ensure_database_ready()
    if not arg:
        return send_message(chat_id, "مثال: /delete model 12")
    parts = arg.split(maxsplit=1)
    type_ = parts[0]
    id_ = parts[1] if len(parts) > 1 else ""
    code, out = run_phdler(["delete", type_], input_text=id_)
    send_message(chat_id, f"نتیجه delete:\n\n{out[:3500]}")


# ---------------------------------------------------------
# 5) Long polling
# ---------------------------------------------------------
def get_updates(offset=None):
    data = {"timeout": 30}
    if offset:
        data["offset"] = offset
    return api("getUpdates", data=data, timeout=40)


def main():
    if not TOKEN:
        raise RuntimeError("BALE_BOT_TOKEN is not set")

    offset = None

    if ADMIN_ID:
        send_message(ADMIN_ID, "ربات بله فعال شد.")

    while True:
        try:
            res = get_updates(offset)
            if not res.get("ok"):
                time.sleep(2)
                continue

            for upd in res.get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message") or upd.get("edited_message")
                if not msg:
                    continue

                chat_id = msg["chat"]["id"]
                text = msg.get("text", "")
                cmd, arg = parse_command(text)

                if cmd == "/start":
                    handle_start(chat_id)
                elif cmd == "/help":
                    handle_help(chat_id)
                elif cmd == "/dlstart":
                    handle_dlstart(chat_id)
                elif cmd == "/custom":
                    handle_custom(chat_id, arg)
                elif cmd == "/add":
                    handle_add(chat_id, arg)
                elif cmd == "/list":
                    handle_list(chat_id, arg)
                elif cmd == "/delete":
                    handle_delete(chat_id, arg)
                else:
                    send_message(chat_id, "دستور نامعتبر: /help را بزن")

        except Exception:
            time.sleep(3)


if __name__ == "__main__":
    main()
