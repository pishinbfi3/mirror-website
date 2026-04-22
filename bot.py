import os
import asyncio
import json
import subprocess
from pathlib import Path
import aiohttp

TOKEN = os.getenv("BALE_BOT_TOKEN")
ALLOWED_CHAT_ID = os.getenv("BALE_CHAT_ID")
ENABLE_TELEGRAM = os.getenv("ENABLE_TELEGRAM", "true").lower() == "true"

BALE_API_URL = f"https://tapi.bale.ai/bot{TOKEN}"

DOWNLOADER_DIR = Path.cwd() / "downloader"
PHDLER_SCRIPT = DOWNLOADER_DIR / "phdler.py"

LOG_DIR = DOWNLOADER_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "run.log"


class BaleBot:
    def __init__(self, token, allowed_chat_id=None):
        self.token = token
        self.allowed_chat_id = str(allowed_chat_id) if allowed_chat_id else None
        self.offset = 0

    async def _call_api(self, method, payload=None):
        url = f"{BALE_API_URL}/{method}"
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                return data

    async def send_message(self, chat_id, text):
        await self._call_api("sendMessage", {"chat_id": chat_id, "text": text})

    async def get_updates(self):
        payload = {"offset": self.offset, "timeout": 10}
        data = await self._call_api("getUpdates", payload)
        if data and data.get("ok"):
            return data["result"]
        return []

    def _is_allowed(self, chat_id):
        if not self.allowed_chat_id:
            return True
        return str(chat_id) == self.allowed_chat_id

    async def handle_update(self, update):
        if "message" not in update:
            return

        msg = update["message"]
        chat_id = msg["chat"]["id"]
        text = msg.get("text", "")

        if not self._is_allowed(chat_id):
            await self.send_message(chat_id, "Access denied.")
            return

        if text.startswith("/start"):
            await self.cmd_start(chat_id)

        elif text.startswith("/run"):
            parts = text.split(" ", 2)
            if len(parts) >= 2:
                action = parts[1]
                args = parts[2] if len(parts) == 3 else ""
                await self.cmd_run(chat_id, action, args)

        elif text.startswith("/log"):
            await self.cmd_log(chat_id)

    async def cmd_start(self, chat_id):
        msg = (
            "Commands:\n"
            "/run <action> <args>\n"
            "/log\n"
        )
        await self.send_message(chat_id, msg)

    async def cmd_run(self, chat_id, action, args):
        await self.send_message(chat_id, f"Running: {action} {args}")

        cmd = ["python3", str(PHDLER_SCRIPT), action]
        if args:
            cmd.extend(args.split())

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=DOWNLOADER_DIR,
            text=True
        )

        with LOG_FILE.open("a") as log:
            for line in process.stdout:
                log.write(line)
                await self.send_message(chat_id, line)

        exit_code = process.wait()
        await self.send_message(chat_id, f"Completed with exit code {exit_code}")

    async def cmd_log(self, chat_id):
        if not LOG_FILE.exists():
            await self.send_message(chat_id, "No logs yet.")
            return

        lines = LOG_FILE.read_text().splitlines()[-20:]
        await self.send_message(chat_id, "\n".join(lines))

    async def run(self):
        while True:
            updates = await self.get_updates()
            for update in updates:
                self.offset = update["update_id"] + 1
                await self.handle_update(update)
            await asyncio.sleep(1)


async def main():
    if not ENABLE_TELEGRAM:
        print("Bot disabled.")
        return

    bot = BaleBot(TOKEN, ALLOWED_CHAT_ID)
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
