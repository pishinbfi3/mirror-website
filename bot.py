import os
import shlex
import subprocess
import sys
import requests
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
TOKEN = os.getenv("BALE_BOT_TOKEN")
CHAT_ID = os.getenv("BALE_CHAT_ID")  # optional – restricts bot to a chat
ENABLE_TELEGRAM = os.getenv("ENABLE_TELEGRAM", "true").lower() == "true"

# بله API base URL
BALE_API_URL = f"https://tapi.bale.ai/bot{TOKEN}"

# Path to the downloader directory
DOWNLOADER_DIR = Path.cwd() / "a-downloader-python-master"
PHDLER_SCRIPT = DOWNLOADER_DIR / "phdler.py"

LOG_DIR = DOWNLOADER_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "bot.log"


class BaleBot:
    def __init__(self, token: str, allowed_chat_id: Optional[str] = None):
        self.token = token
        self.allowed_chat_id = allowed_chat_id
        self.base_url = f"https://tapi.bale.ai/bot{token}"
        self.offset = 0
        self.running = True
    
    def _call_api(self, method: str, params: Dict[str, Any] = None) -> Optional[Dict]:
        """فراخوانی API بله"""
        url = f"{self.base_url}/{method}"
        try:
            response = requests.post(url, json=params or {}, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if data.get("ok"):
                    return data
                else:
                    print(f"API error: {data.get('description')}")
            return None
        except Exception as e:
            print(f"API call failed: {e}")
            return None
    
    async def send_message(self, chat_id: int, text: str) -> bool:
        """ارسال پیام به کاربر"""
        result = self._call_api("sendMessage", {
            "chat_id": chat_id,
            "text": text
        })
        return result is not None
    
    async def get_updates(self) -> list:
        """دریافت آپدیت‌های جدید"""
        result = self._call_api("getUpdates", {
            "offset": self.offset,
            "timeout": 30
        })
        
        if result and result.get("result"):
            updates = result["result"]
            if updates:
                self.offset = updates[-1]["update_id"] + 1
            return updates
        return []
    
    def _is_allowed(self, chat_id: int) -> bool:
        """بررسی مجوز چت"""
        if self.allowed_chat_id and str(chat_id) != self.allowed_chat_id:
            return False
        return True
    
    async def handle_update(self, update: Dict):
        """پردازش یک آپدیت"""
        if "message" not in update:
            return
        
        message = update["message"]
        chat_id = message["chat"]["id"]
        
        if not self._is_allowed(chat_id):
            return
        
        if "text" not in message:
            return
        
        text = message["text"]
        if not text.startswith("/"):
            return
        
        # پردازش کامندها
        parts = text.split()
        command = parts[0].lower()
        args = parts[1:] if len(parts) > 1 else []
        
        if command == "/start":
            await self.cmd_start(chat_id)
        elif command == "/run" and args:
            await self.cmd_run(chat_id, args)
        elif command == "/log":
            await self.cmd_log(chat_id)
    
    async def cmd_start(self, chat_id: int):
        """دستور start"""
        help_text = (
            "به ربات دانلودر خوش آمدید!\n\n"
            "دستورات موجود:\n"
            "/run <action> [args...] - اجرای phdler.py\n"
            "/log - نمایش ۲۰ خط آخر لاگ"
        )
        await self.send_message(chat_id, help_text)
    
    async def cmd_run(self, chat_id: int, args: list):
        """دستور run"""
        if not args:
            await self.send_message(chat_id, "Usage: /run <action> [args...]")
            return
        
        action = args[0]
        cmd_args = args[1:]
        
        await self.send_message(chat_id, f"در حال اجرا: {action} {' '.join(cmd_args)}")
        
        # اجرای فرآیند
        cmd = [sys.executable, str(PHDLER_SCRIPT), action] + cmd_args
        process = subprocess.Popen(
            cmd,
            cwd=DOWNLOADER_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        # ارسال خروجی خط به خط
        for line in process.stdout:
            line = line.rstrip()
            # ذخیره در لاگ فایل
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            
            # ارسال به بله (تقسیم به بخش‌های ۴۰۰۰ کاراکتری)
            for i in range(0, len(line), 4000):
                await self.send_message(chat_id, line[i:i+4000])
        
        return_code = process.wait()
        await self.send_message(chat_id, f"فرآیند با کد خروج {return_code} به پایان رسید.")
    
    async def cmd_log(self, chat_id: int):
        """دستور log"""
        if not LOG_FILE.exists():
            await self.send_message(chat_id, "فایل لاگ یافت نشد.")
            return
        
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()[-20:]
        
        log_text = "".join(lines) or "لاگ خالی است."
        await self.send_message(chat_id, log_text)
    
    async def run(self):
        """حلقه اصلی ربات"""
        print("ربات بله در حال اجرا است...")
        
        while self.running:
            try:
                updates = await self.get_updates()
                for update in updates:
                    await self.handle_update(update)
                await asyncio.sleep(1)
            except Exception as e:
                print(f"Error in main loop: {e}")
                await asyncio.sleep(5)


async def main():
    if not ENABLE_TELEGRAM:
        print("Telegram integration is disabled")
        return
    
    if not TOKEN:
        print("Error: BALE_BOT_TOKEN environment variable is not set.")
        sys.exit(1)
    
    bot = BaleBot(TOKEN, CHAT_ID)
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
