"""Telegram bot for managing PornHub-downloader-python.

This script uses the `python-telegram-bot` library to expose a simple
interface for the downloader. It supports the following commands:

* ``/start`` – Show a welcome message.
* ``/run <action> [args...]`` – Execute ``phdler.py`` with the given
  ``action`` and optional arguments. The output is streamed back to the
  user and also written to a log file.
* ``/log`` – Send the last few lines of the log file.

Configuration is performed via environment variables:

* ``BALE_BOT_TOKEN`` – Telegram bot token (required).
* ``BALE_CHAT_ID`` – Chat ID where the bot is allowed to respond (optional).
* ``ENABLE_TELEGRAM`` – Set to ``true`` to start the bot (default: ``true``).

All logs are stored under the ``logs`` directory. The bot runs the
downloader in a subprocess, captures ``stdout``/``stderr`` and forwards
the output to the user in real‑time.
"""

import os
import shlex
import subprocess
import sys
from pathlib import Path

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
TOKEN = os.getenv("BALE_BOT_TOKEN")
CHAT_ID = os.getenv("BALE_CHAT_ID")  # optional – restricts bot to a chat
ENABLE_TELEGRAM = os.getenv("ENABLE_TELEGRAM", "true").lower() == "true"

# Path to the downloader directory – assumed to be the current working
# directory when the bot is started. ``phdler.py`` resides here.
DOWNLOADER_DIR = Path.cwd()
PHDLER_SCRIPT = DOWNLOADER_DIR / "phdler.py"

LOG_DIR = DOWNLOADER_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "bot.log"


def _restricted(func):
    """Decorator that restricts the bot to a specific chat if ``CHAT_ID`` is set.

    If ``CHAT_ID`` is not defined, the bot will respond to any chat.
    """

    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if CHAT_ID and str(update.effective_chat.id) != CHAT_ID:
            # Silently ignore messages from unauthorized chats.
            return
        return await func(update, context)

    return wrapper


@_restricted
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the ``/start`` command – send a short help message."""
    help_text = (
        "Welcome! I can manage the PornHub downloader for you.\n\n"
        "Available commands:\n"
        "/run <action> [args...] – Execute ``phdler.py``. Example: ``/run start``\n"
        "/log – Show the last 20 lines of the bot log."
    )
    await update.message.reply_text(help_text)


def _run_phdler(action: str, args: list[str]) -> subprocess.Popen:
    """Start ``phdler.py`` as a subprocess.

    The command is built as ``python3 phdler.py <action> [args...]``.
    ``stdout`` and ``stderr`` are merged and streamed line‑by‑line.
    """
    cmd = [sys.executable, str(PHDLER_SCRIPT), action] + args
    # ``text=True`` gives us strings instead of bytes.
    return subprocess.Popen(
        cmd,
        cwd=DOWNLOADER_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )


@_restricted
async def run(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the ``/run`` command.

    The user supplies an action and optional arguments. The bot executes the
    downloader and streams the output back to the chat. All output is also
    appended to ``logs/bot.log``.
    """
    if not context.args:
        await update.message.reply_text("Usage: /run <action> [args...]")
        return

    action = context.args[0]
    args = context.args[1:]

    await update.message.reply_text(f"Running: {action} {' '.join(args)}")

    process = _run_phdler(action, args)
    # Stream output line by line.
    for line in process.stdout:
        line = line.rstrip()
        # Write to log file.
        LOG_FILE.write_text(LOG_FILE.read_text(encoding="utf-8") + line + "\n", encoding="utf-8")
        # Send to Telegram – split long messages to respect Telegram limits.
        if len(line) > 4000:
            # Break into chunks of 4000 characters.
            for i in range(0, len(line), 4000):
                await update.message.reply_text(line[i : i + 4000])
        else:
            await update.message.reply_text(line)

    return_code = process.wait()
    await update.message.reply_text(f"Process finished with exit code {return_code}.")


@_restricted
async def log(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the last 20 lines of the log file to the user."""
    if not LOG_FILE.exists():
        await update.message.reply_text("Log file not found.")
        return
    lines = LOG_FILE.read_text(encoding="utf-8").splitlines()[-20:]
    await update.message.reply_text("\n".join(lines) or "Log is empty.")


async def main() -> None:
    if not ENABLE_TELEGRAM:
        print("Telegram integration is disabled (ENABLE_TELEGRAM=false).")
        return
    if not TOKEN:
        print("Error: BALE_BOT_TOKEN environment variable is not set.")
        sys.exit(1)

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("run", run))
    app.add_handler(CommandHandler("log", log))

    print("Bot is starting…")
    await app.run_polling()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())

