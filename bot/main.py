#!/usr/bin/env python3
"""Main entry point for Bale SSH Bot with stateful executor and process manager."""

import sys
import time
import os
import traceback
import glob
from datetime import datetime

from .config import BotConfig
from .handler import BaleBotHandler


def setup_environment():
    """Ensure /tmp directory exists and log startup."""
    os.makedirs("/tmp", exist_ok=True)
    with open("/tmp/bale-bot-startup.log", "w") as f:
        f.write(f"Bot started at {datetime.now().isoformat()}\n")
        f.write(f"Python: {sys.version}\n")
        f.write(f"PID: {os.getpid()}\n")


def cleanup_old_files():
    patterns = [
        "/tmp/bale_output_*.txt",
        "/tmp/command-output-*.txt",
        "/tmp/bale_download_*",
        "/tmp/*.part*",           # قطعات split
        "/tmp/*.zip"              # فایل‌های zip موقت
    ]
    now = time.time()
    for pattern in patterns:
        for filepath in glob.glob(pattern):
            try:
                if now - os.path.getmtime(filepath) > 3600:
                    os.unlink(filepath)
            except Exception:
                pass

def log(msg: str):
    """Print message with flush."""
    print(msg, flush=True)


def main():
    """Main bot loop."""
    log("🤖 Bale SSH Bot starting (stateful executor + process manager)...")
    setup_environment()
    cleanup_old_files()

    try:
        config = BotConfig.from_env()
        log(f"✅ Config loaded – Chat ID: {config.chat_id[:10]}...")
    except ValueError as e:
        log(f"❌ Config error: {e}")
        sys.exit(1)

    handler = BaleBotHandler(config)
    log("✅ Bot handler initialized with process manager")

    # Start from latest updates, ignore old history
    offset = 0
    current_time = time.time()
    log("📝 Starting with offset 0, ignoring messages older than 30 seconds")

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

                # Ignore messages older than 30 seconds
                msg_date = message.get("date", 0)
                if current_time - msg_date > 30:
                    log(f"⏭️ Skipping old message from {datetime.fromtimestamp(msg_date)}")
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

                # Clean up old jobs and temporary files every 10 commands
                if processed % 10 == 0:
                    handler.process_manager.cleanup_old()
                    cleanup_old_files()

            handler.save_offset(offset)

        except KeyboardInterrupt:
            log("⚠️ Received interrupt, stopping...")
            break
        except Exception as e:
            log(f"❌ Unexpected error in main loop: {e}")
            traceback.print_exc(file=sys.stdout)
            time.sleep(5)

    # Final cleanup
    handler.close()
    cleanup_old_files()
    log(f"\n📊 Summary: processed {processed} commands. Bot stopped.")
    sys.exit(0)


if __name__ == "__main__":
    main()
