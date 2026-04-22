#!/usr/bin/env python3
"""Main entry point for Bale SSH Bot with persistent shell and stop command."""

import sys
import time
import os
import traceback
from datetime import datetime

from .config import BotConfig
from .handler import BaleBotHandler


def setup_environment():
    os.makedirs("/tmp", exist_ok=True)
    with open("/tmp/bale-bot-startup.log", "w") as f:
        f.write(f"Bot started at {datetime.now().isoformat()}\nPython: {sys.version}\nPID: {os.getpid()}\n")

def cleanup_old_files():
    import glob
    patterns = ["/tmp/bale_output_*.txt", "/tmp/command-output-*.txt"]
    now = time.time()
    for pattern in patterns:
        for f in glob.glob(pattern):
            try:
                if now - os.path.getmtime(f) > 3600:
                    os.unlink(f)
            except Exception:
                pass

def log(msg: str):
    """Print with flush to ensure visibility in GitHub Actions."""
    print(msg, flush=True)

def main():
    log("🤖 Bale SSH Bot starting (enhanced version)...")
    setup_environment()
    cleanup_old_files()

    try:
        config = BotConfig.from_env()
        log(f"✅ Config loaded – Chat ID: {config.chat_id[:10]}...")
    except ValueError as e:
        log(f"❌ Config error: {e}")
        sys.exit(1)

    handler = BaleBotHandler(config)
    log("✅ Bot handler initialized with persistent shell")
    offset = handler.get_offset()
    log(f"📝 Last offset: {offset}")

    processed = 0
    stop_requested = False

    while not stop_requested:
        try:
            updates = handler.get_updates(offset)
            if not updates:
                time.sleep(1)
                continue

            for update in updates:
                update_id = update.get("update_id", 0)
                offset = max(offset, update_id + 1)

                message = update.get("message") or update.get("edited_message")
                if not message:
                    continue

                chat = message.get("chat", {})
                if str(chat.get("id")) != config.chat_id:
                    log(f"⚠️ Ignoring chat {chat.get('id')}")
                    continue

                # Handle document uploads
                if message.get("document"):
                    log("📄 Received a document, uploading...")
                    response = handler.handle_document(message)
                    handler.send_message(response, message.get("message_id"))
                    continue

                text = message.get("text") or message.get("caption", "").strip()
                if not text:
                    continue

                log(f"💬 Processing: {text[:50]}...")
                # Check for stop command
                if text.strip().lower() == "/stop":
                    handler.send_message("🛑 Stopping bot now...")
                    stop_requested = True
                    break

                response, file_path = handler.process_command(text)
                handler.send_message(response, message.get("message_id"))
                if file_path and os.path.exists(file_path):
                    handler.send_file(file_path, f"Output for: {text[:100]}")
                    os.unlink(file_path)
                processed += 1
                log(f"✅ Response sent (total processed: {processed})")

            handler.save_offset(offset)
        except Exception as e:
            log(f"❌ Unexpected error in main loop: {e}")
            traceback.print_exc(file=sys.stdout)
            time.sleep(5)

    handler.close()
    log(f"\n📊 Summary: processed {processed} commands. Bot stopped.")
    sys.exit(0)

if __name__ == "__main__":
    main()
