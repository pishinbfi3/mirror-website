import os
import time
import json
import math
import shutil
import tempfile
import subprocess
from pathlib import Path
import requests

TOKEN = os.getenv("BALE_BOT_TOKEN")
BASE_URL = f"https://tapi.bale.ai/bot{TOKEN}"
ADMIN_ID = os.getenv("ADMIN_ID", "")  # اختیاری
WORKDIR = Path(os.getenv("WORKDIR", "/tmp/phdler_workdir"))
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", "/tmp/phdler_downloads"))
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

WORKDIR.mkdir(parents=True, exist_ok=True)
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


def api(method, data=None, files=None, timeout=120):
    url = f"{BASE_URL}/{method}"
    if files:
        return requests.post(url, data=data, files=files, timeout=timeout).json()
    return requests.post(url, data=data, timeout=timeout).json()


def send_message(chat_id, text):
    return api("sendMessage", data={
        "chat_id": chat_id,
        "text": text
    })


def send_document(chat_id, file_path, caption=None):
    file_path = Path(file_path)
    if file_path.stat().st_size <= MAX_FILE_SIZE:
        with open(file_path, "rb") as f:
            return api(
                "sendDocument",
                data={
                    "chat_id": chat_id,
                    "caption": caption or ""
                },
                files={"document": f}
            )
    else:
        parts = split_file(file_path, MAX_FILE_SIZE)
        responses = []
        for i, part in enumerate(parts, 1):
            with open(part, "rb") as f:
                resp = api(
                    "sendDocument",
                    data={
                        "chat_id": chat_id,
                        "caption": f"{caption or ''} (part {i}/{len(parts)})"
                    },
                    files={"document": f}
                )
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


def run_phdler(args, input_text=None, cwd=None):
    cmd = ["python3", "phdler.py"] + args
    proc = subprocess.run(
        cmd,
        input=input_text,
        capture_output=True,
        text=True,
        cwd=cwd
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
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""
    return cmd, arg


def handle_start(chat_id):
    msg = (
        "سلام!\n\n"
        "این ربات برای کار با phdler.py ساخته شده است.\n\n"
        "دستورات:\n"
        "/start - نمایش راهنما\n"
        "/help - راهنمای کامل\n"
        "/dlstart - اجرای start اصلی پروژه\n"
        "/custom <url|batch> - دانلود سفارشی\n"
        "/add <model|pornstar|channel|user|playlist|batch> <value>\n"
        "/list <model|pornstar|channel|user|playlist|all>\n"
        "/delete <model|pornstar|channel|user|playlist> <id>\n\n"
        "نکته: اگر فایل بیش از 10MB شد، ربات آن را تکه‌تکه ارسال می‌کند."
    )
    send_message(chat_id, msg)


def handle_help(chat_id):
    help_text = (
        "راهنمای ربات:\n\n"
        "/dlstart\n"
        "شروع پردازش دانلودهای پروژه\n\n"
        "/custom <url|batch>\n"
        "دانلود یک URL خاص یا batch\n\n"
        "/add <type> <value>\n"
        "افزودن آیتم جدید\n\n"
        "/list <type>\n"
        "نمایش آیتم‌ها\n\n"
        "/delete <type> <id>\n"
        "حذف آیتم بر اساس ID\n"
    )
    send_message(chat_id, help_text)


def handle_dlstart(chat_id):
    code, out = run_phdler(["start"], cwd=str(WORKDIR))
    send_message(chat_id, f"نتیجه اجرای start:\n\n{out[:3500] if out else 'بدون خروجی'}")


def handle_custom(chat_id, arg):
    if not arg:
        send_message(chat_id, "لطفاً یک مقدار برای custom بفرستید: URL یا batch")
        return
    code, out = run_phdler(["custom", arg], cwd=str(WORKDIR))
    send_message(chat_id, f"نتیجه custom:\n\n{out[:3500] if out else 'بدون خروجی'}")


def handle_add(chat_id, arg):
    if not arg:
        send_message(chat_id, "مثال:\n/add model <url>\n/add batch <file-or-input>")
        return
    parts = arg.split(maxsplit=1)
    item_type = parts[0]
    value = parts[1] if len(parts) > 1 else ""
    if not value and item_type != "batch":
        send_message(chat_id, "مقدار ورودی برای add خالی است.")
        return
    code, out = run_phdler(["add", item_type], input_text=value, cwd=str(WORKDIR))
    send_message(chat_id, f"نتیجه add:\n\n{out[:3500] if out else 'بدون خروجی'}")


def handle_list(chat_id, arg):
    if not arg:
        send_message(chat_id, "مثال:\n/list all")
        return
    code, out = run_phdler(["list", arg], cwd=str(WORKDIR))
    send_message(chat_id, f"نتیجه list:\n\n{out[:3500] if out else 'بدون خروجی'}")


def handle_delete(chat_id, arg):
    if not arg:
        send_message(chat_id, "مثال:\n/delete model 12")
        return
    parts = arg.split(maxsplit=1)
    item_type = parts[0]
    item_id = parts[1] if len(parts) > 1 else ""
    if not item_id:
        send_message(chat_id, "شناسه (ID) را وارد کنید.")
        return

    # چون CLI اصلی حذف از stdin می‌گیرد، اینجا ID را به stdin می‌دهیم
    code, out = run_phdler(["delete", item_type], input_text=item_id, cwd=str(WORKDIR))
    send_message(chat_id, f"نتیجه delete:\n\n{out[:3500] if out else 'بدون خروجی'}")


def get_updates(offset=None):
    data = {"timeout": 30}
    if offset:
        data["offset"] = offset
    return api("getUpdates", data=data, timeout=40)


def main():
    if not TOKEN:
        raise RuntimeError("BALE_BOT_TOKEN is not set")

    offset = None
    send_message(ADMIN_ID or "0", "ربات بله فعال شد.") if ADMIN_ID else None

    while True:
        try:
            res = get_updates(offset)
            if not res.get("ok"):
                time.sleep(2)
                continue

            for upd in res.get("result", []):
                offset = upd["update_id"] + 1

                message = upd.get("message") or upd.get("edited_message")
                if not message:
                    continue

                chat_id = message["chat"]["id"]
                text = message.get("text", "")
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
                    send_message(chat_id, "دستور نامعتبر است. /start را بزنید.")

        except Exception as e:
            time.sleep(3)


if __name__ == "__main__":
    main()
  
