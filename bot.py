import os
import asyncio
import json
import subprocess
import zipfile
import shutil
from pathlib import Path
from datetime import datetime
import aiohttp

TOKEN = os.getenv("BALE_BOT_TOKEN")
ALLOWED_CHAT_ID = os.getenv("BALE_CHAT_ID")
# اصلاح این خط:
ENABLE_TELEGRAM = os.getenv("ENABLE_TELEGRAM", "true")
ENABLE_TELEGRAM = ENABLE_TELEGRAM.strip().lower() == "true" if ENABLE_TELEGRAM else True
ALLOWED_CHAT_ID = os.getenv("BALE_CHAT_ID")
ENABLE_TELEGRAM = os.getenv("ENABLE_TELEGRAM", "true").lower() == "true"

BALE_API_URL = f"https://tapi.bale.ai/bot{TOKEN}"
DOWNLOADER_DIR = Path.cwd() / "downloader"
DL_SCRIPT = DOWNLOADER_DIR / "dl.py"
LOG_DIR = DOWNLOADER_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "run.log"

# پوشه موقت برای فایل‌های split
TEMP_DIR = DOWNLOADER_DIR / "temp_split"
TEMP_DIR.mkdir(exist_ok=True)

# حداکثر حجم هر قطعه (۱۰ مگابایت)
CHUNK_SIZE = 10 * 1024 * 1024  # 10 MB
# تأخیر بین ارسال قطعات (برای رعایت rate limit)
SEND_DELAY = 1.0  # ثانیه


class ZipSplitter:
    """یک فایل را zip کرده و به قطعات تقسیم می‌کند."""
    
    def __init__(self, file_path: Path, chunk_size: int = CHUNK_SIZE, temp_dir: Path = TEMP_DIR):
        self.file_path = file_path
        self.chunk_size = chunk_size
        self.temp_dir = temp_dir
        self.zip_path = None
        self.part_paths = []
    
    def create_zip(self) -> Path:
        """فایل اصلی را zip می‌کند و مسیر فایل zip را برمی‌گرداند."""
        zip_name = self.file_path.stem + ".zip"
        self.zip_path = self.temp_dir / zip_name
        with zipfile.ZipFile(self.zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.write(self.file_path, arcname=self.file_path.name)
        return self.zip_path
    
    def split_zip(self) -> list:
        """فایل zip را به قطعات با اندازه مشخص تقسیم می‌کند."""
        if not self.zip_path or not self.zip_path.exists():
            self.create_zip()
        
        part_pattern = self.zip_path.stem + ".part"
        with open(self.zip_path, 'rb') as f:
            part_num = 1
            while True:
                chunk = f.read(self.chunk_size)
                if not chunk:
                    break
                part_path = self.temp_dir / f"{part_pattern}.{part_num:03d}"
                with open(part_path, 'wb') as p:
                    p.write(chunk)
                self.part_paths.append(part_path)
                part_num += 1
        return self.part_paths
    
    def cleanup(self):
        """فایل‌های موقت (zip و قطعات) را حذف می‌کند."""
        if self.zip_path and self.zip_path.exists():
            self.zip_path.unlink()
        for p in self.part_paths:
            if p.exists():
                p.unlink()
        self.part_paths.clear()


class BaleBot:
    def __init__(self, token, allowed_chat_id=None):
        self.token = token
        self.allowed_chat_id = str(allowed_chat_id) if allowed_chat_id else None
        self.offset = 0
    
    async def _call_api(self, method, payload=None, files=None):
        url = f"{BALE_API_URL}/{method}"
        async with aiohttp.ClientSession() as session:
            if files:
                # ارسال multipart/form-data برای فایل
                data = aiohttp.FormData()
                for key, value in (payload or {}).items():
                    data.add_field(key, str(value))
                for file_field, file_path in files.items():
                    data.add_field(file_field, open(file_path, 'rb'), filename=Path(file_path).name)
                async with session.post(url, data=data) as resp:
                    if resp.status != 200:
                        return None
                    return await resp.json()
            else:
                async with session.post(url, json=payload) as resp:
                    if resp.status != 200:
                        return None
                    return await resp.json()
    
    async def send_message(self, chat_id, text):
        await self._call_api("sendMessage", {"chat_id": chat_id, "text": text})
    
    async def send_document(self, chat_id, file_path: Path, caption=""):
        """ارسال یک فایل به عنوان سند (با پشتیبانی از zip و غیره)"""
        files = {"document": str(file_path)}
        payload = {"chat_id": chat_id, "caption": caption}
        return await self._call_api("sendDocument", payload, files)
    
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
            "🤖 *pornhub Downloader Bot*\n\n"
            "دستورات:\n"
            "/run custom <url>  - دانلود ویدئو و ارسال split شده\n"
            "/run start         - اجرای دانلود همه آیتم‌های جدید (فقط ذخیره در دیسک)\n"
            "/log               - نمایش ۲۰ خط آخر لاگ\n"
        )
        await self.send_message(chat_id, msg)
    
    async def find_downloaded_file(self, handpicked_dir: Path, timeout=30) -> Path:
        """پیدا کردن آخرین فایل اضافه شده در پوشه handpicked (در ۳۰ ثانیه اخیر)"""
        start_time = datetime.now()
        last_file = None
        while (datetime.now() - start_time).seconds < timeout:
            files = list(handpicked_dir.glob("*"))
            if files:
                # جدیدترین فایل بر اساس زمان ایجاد
                newest = max(files, key=lambda f: f.stat().st_ctime)
                if last_file != newest:
                    last_file = newest
                    # اگر فایل در حال دانلود است (حجمش ثابت نشده) کمی صبر می‌کنیم
                    await asyncio.sleep(2)
                    if newest.stat().st_size > 0:
                        return newest
            await asyncio.sleep(1)
        return None
    
    async def cmd_run(self, chat_id, action, args):
        await self.send_message(chat_id, f"▶️ در حال اجرا: {action} {args}")
        # اجرای dl.py
        cmd = ["python3", str(DL_SCRIPT), action]
        if args:
            cmd.extend(args.split())
        
        # اگر action == custom است، قبل از اجرا پوشه handpicked را پاک می‌کنیم تا فقط فایل جدید باقی بماند
        handpicked_dir = DOWNLOADER_DIR / "handpicked"
        handpicked_dir.mkdir(exist_ok=True)
        if action == "custom":
            for f in handpicked_dir.glob("*"):
                f.unlink()
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=DOWNLOADER_DIR
        )
        # خواندن خروجی خط به خط و ارسال به کاربر (اختیاری)
        async for line in process.stdout:
            decoded = line.decode().strip()
            if decoded:
                # لاگ را در فایل ذخیره می‌کنیم
                with LOG_FILE.open("a") as log_f:
                    log_f.write(decoded + "\n")
                # برای جلوگیری از flood، فقط خطوط مهم را به کاربر نشان می‌دهیم
                if "ERROR" in decoded or "completed" in decoded.lower():
                    await self.send_message(chat_id, decoded[:4000])
        await process.wait()
        exit_code = process.returncode
        await self.send_message(chat_id, f"✅ دانلود با کد خروج {exit_code} پایان یافت.")
        
        # اگر action custom بود و دانلود موفق بود، فایل را split و ارسال کن
        if action == "custom" and exit_code == 0:
            downloaded_file = await self.find_downloaded_file(handpicked_dir)
            if not downloaded_file:
                await self.send_message(chat_id, "⚠️ فایل دانلود شده پیدا نشد.")
                return
            await self.send_message(chat_id, f"📦 فایل یافت شد: {downloaded_file.name}\nدر حال آماده‌سازی برای ارسال...")
            
            splitter = ZipSplitter(downloaded_file, chunk_size=CHUNK_SIZE, temp_dir=TEMP_DIR)
            try:
                zip_path = splitter.create_zip()
                parts = splitter.split_zip()
                total_parts = len(parts)
                await self.send_message(chat_id, f"🗜 فایل zip شد. تعداد قطعات: {total_parts}\nشروع ارسال...")
                for idx, part in enumerate(parts, 1):
                    caption = f"بخش {idx} از {total_parts} - {part.name}"
                    await self.send_document(chat_id, part, caption=caption)
                    await asyncio.sleep(SEND_DELAY)  # rate limit
                await self.send_message(chat_id, "✅ تمام قطعات ارسال شدند.")
            except Exception as e:
                await self.send_message(chat_id, f"❌ خطا در split یا ارسال: {str(e)}")
            finally:
                splitter.cleanup()
                # فایل اصلی را پاک می‌کنیم تا دیسک پر نشود (اختیاری)
                if downloaded_file.exists():
                    downloaded_file.unlink()
    
    async def cmd_log(self, chat_id):
        if not LOG_FILE.exists():
            await self.send_message(chat_id, "هیچ لاگی وجود ندارد.")
            return
        lines = LOG_FILE.read_text().splitlines()[-20:]
        await self.send_message(chat_id, "\n".join(lines))
    
    async def run(self):
        while True:
            try:
                updates = await self.get_updates()
                for update in updates:
                    self.offset = update["update_id"] + 1
                    await self.handle_update(update)
            except Exception as e:
                print(f"Error in polling: {e}")
            await asyncio.sleep(1)


async def main():
    if not ENABLE_TELEGRAM:
        print("Bot disabled.")
        return
    if not TOKEN:
        print("BALE_BOT_TOKEN not set.")
        return
    bot = BaleBot(TOKEN, ALLOWED_CHAT_ID)
    await bot.run()

if __name__ == "__main__":
    asyncio.run(main())
