import os
import asyncio
from pathlib import Path
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

PHDLER_SCRIPT = "phdler.py"

async def run(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /run <url>")
        return

    url = context.args[0]

    await update.message.reply_text("⏳ در حال دانلود...")

    # اجرای دانلود
    proc = await asyncio.create_subprocess_exec(
        "python3", PHDLER_SCRIPT, url,
        stdout=asyncio.subprocess.PIPE
    )

    out, err = await proc.communicate()

    # خواندن خروجی فایل‌ها
    parts = []
    for line in out.decode().splitlines():
        if line.strip().endswith(".part001") or ".part" in line:
            parts.append(line.strip())

    # ارسال فایل‌ها با rate limit
    await update.message.reply_text("📤 ارسال فایل‌ها...")

    for part in parts:
        await update.message.reply_document(open(part, "rb"))
        await asyncio.sleep(4)   # rate limit

    await update.message.reply_text("✔️ تمام شد.")

def main():
    app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()
    app.add_handler(CommandHandler("run", run))
    app.run_polling()

if __name__ == "__main__":
    main()
