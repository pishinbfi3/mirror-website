import os
import asyncio
import subprocess
import zipfile
from pathlib import Path
from datetime import datetime
import aiohttp
import sys

# Add downloader directory to Python path
sys.path.insert(0, str(Path.cwd() / "downloader"))

# Environment variables
TOKEN = os.getenv("BALE_BOT_TOKEN")
ALLOWED_CHAT_ID = os.getenv("BALE_CHAT_ID")
ENABLE_TELEGRAM = os.getenv("ENABLE_TELEGRAM", "true")
ENABLE_TELEGRAM = ENABLE_TELEGRAM.strip().lower() == "true" if ENABLE_TELEGRAM else True

# API endpoint
BALE_API_URL = f"https://tapi.bale.ai/bot{TOKEN}"

# Directory setup - FIXED for your structure
BASE_DIR = Path.cwd()
DOWNLOADER_DIR = BASE_DIR / "downloader"  # Points to downloader folder
DL_SCRIPT = DOWNLOADER_DIR / "dl.py"
LOG_DIR = DOWNLOADER_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "run.log"

# Temporary directories for split files
TEMP_DIR = DOWNLOADER_DIR / "temp_split"
TEMP_DIR.mkdir(exist_ok=True)

# Configuration
CHUNK_SIZE = 10 * 1024 * 1024  # 10 MB
SEND_DELAY = 1.0  # Delay between sending chunks (seconds)


class ZipSplitter:
    """Zip a file and split into smaller chunks"""
    
    def __init__(self, file_path: Path, chunk_size: int = CHUNK_SIZE, temp_dir: Path = TEMP_DIR):
        self.file_path = file_path
        self.chunk_size = chunk_size
        self.temp_dir = temp_dir
        self.zip_path = None
        self.part_paths = []
    
    def create_zip(self) -> Path:
        """Create zip archive of the original file"""
        zip_name = self.file_path.stem + ".zip"
        self.zip_path = self.temp_dir / zip_name
        with zipfile.ZipFile(self.zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.write(self.file_path, arcname=self.file_path.name)
        return self.zip_path
    
    def split_zip(self) -> list:
        """Split zip file into chunks of specified size"""
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
        """Remove temporary zip and part files"""
        if self.zip_path and self.zip_path.exists():
            self.zip_path.unlink()
        for p in self.part_paths:
            if p.exists():
                p.unlink()
        self.part_paths.clear()


class BaleBot:
    """Bale Telegram Bot handler"""
    
    def __init__(self, token, allowed_chat_id=None):
        self.token = token
        self.allowed_chat_id = str(allowed_chat_id) if allowed_chat_id else None
        self.offset = 0
    
    async def _call_api(self, method, payload=None, files=None):
        """Call Bale API with optional file upload"""
        url = f"{BALE_API_URL}/{method}"
        async with aiohttp.ClientSession() as session:
            if files:
                # Multipart form data for file upload
                data = aiohttp.FormData()
                if payload:
                    for key, value in payload.items():
                        data.add_field(key, str(value))
                for file_field, file_path in files.items():
                    data.add_field(file_field, open(file_path, 'rb'), filename=Path(file_path).name)
                async with session.post(url, data=data) as resp:
                    if resp.status != 200:
                        return None
                    return await resp.json()
            else:
                # JSON payload
                async with session.post(url, json=payload) as resp:
                    if resp.status != 200:
                        return None
                    return await resp.json()
    
    async def send_message(self, chat_id, text):
        """Send text message to chat"""
        await self._call_api("sendMessage", {"chat_id": chat_id, "text": text})
    
    async def send_document(self, chat_id, file_path: Path, caption=""):
        """Send file as document"""
        files = {"document": str(file_path)}
        payload = {"chat_id": chat_id, "caption": caption}
        return await self._call_api("sendDocument", payload, files)
    
    async def get_updates(self):
        """Get new updates from bot"""
        payload = {"offset": self.offset, "timeout": 10}
        data = await self._call_api("getUpdates", payload)
        if data and data.get("ok"):
            return data["result"]
        return []
    
    def _is_allowed(self, chat_id):
        """Check if chat is allowed to use bot"""
        if not self.allowed_chat_id:
            return True
        return str(chat_id) == self.allowed_chat_id
    
    async def handle_update(self, update):
        """Process incoming update"""
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
        """Send help message"""
        msg = (
            "🤖 *pornhub Downloader Bot*\n\n"
            "Commands:\n"
            "/run custom <url>  - Download video and send as split zip\n"
            "/run start         - Download all new items (save to disk only)\n"
            "/log               - Show last 20 lines of log\n"
        )
        await self.send_message(chat_id, msg)
    
    async def find_downloaded_file(self, handpicked_dir: Path, timeout=30) -> Path:
        """Find the most recently downloaded file in handpicked directory"""
        start_time = datetime.now()
        last_file = None
        
        while (datetime.now() - start_time).seconds < timeout:
            files = list(handpicked_dir.glob("*"))
            if files:
                # Get newest file by creation time
                newest = max(files, key=lambda f: f.stat().st_ctime)
                if last_file != newest:
                    last_file = newest
                    # Wait for download to complete
                    await asyncio.sleep(2)
                    if newest.stat().st_size > 0:
                        return newest
            await asyncio.sleep(1)
        return None
    
    async def cmd_run(self, chat_id, action, args):
        """Execute download command"""
        await self.send_message(chat_id, f"▶️ Running: {action} {args}")
        
        # Prepare command
        cmd = ["python3", str(DL_SCRIPT), action]
        if args:
            cmd.extend(args.split())
        
        # Clear handpicked directory before custom download
        handpicked_dir = DOWNLOADER_DIR / "handpicked"
        handpicked_dir.mkdir(parents=True, exist_ok=True)
        if action == "custom":
            for f in handpicked_dir.glob("*"):
                f.unlink()
        
        # Run downloader process
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=DOWNLOADER_DIR
        )
        
        # Read and log output
        async for line in process.stdout:
            decoded = line.decode().strip()
            if decoded:
                with LOG_FILE.open("a") as log_f:
                    log_f.write(decoded + "\n")
                # Send important messages to user
                if "ERROR" in decoded or "completed" in decoded.lower() or "OUTPUT_DIR" in decoded:
                    await self.send_message(chat_id, decoded[:4000])
        
        await process.wait()
        exit_code = process.returncode
        await self.send_message(chat_id, f"✅ Download completed with exit code {exit_code}")
        
        # If custom download was successful, split and send the file
        if action == "custom" and exit_code == 0:
            downloaded_file = await self.find_downloaded_file(handpicked_dir)
            if not downloaded_file:
                await self.send_message(chat_id, "⚠️ Downloaded file not found.")
                return
            
            await self.send_message(chat_id, f"📦 File found: {downloaded_file.name}\nPreparing for sending...")
            
            splitter = ZipSplitter(downloaded_file, chunk_size=CHUNK_SIZE, temp_dir=TEMP_DIR)
            try:
                zip_path = splitter.create_zip()
                parts = splitter.split_zip()
                total_parts = len(parts)
                await self.send_message(chat_id, f"🗜 File zipped. Total parts: {total_parts}\nSending...")
                
                for idx, part in enumerate(parts, 1):
                    caption = f"Part {idx} of {total_parts} - {part.name}"
                    await self.send_document(chat_id, part, caption=caption)
                    await asyncio.sleep(SEND_DELAY)  # Rate limit
                
                await self.send_message(chat_id, "✅ All parts sent successfully.")
            except Exception as e:
                await self.send_message(chat_id, f"❌ Error during split/send: {str(e)}")
            finally:
                splitter.cleanup()
                # Clean up original file
                if downloaded_file.exists():
                    downloaded_file.unlink()
    
    async def cmd_log(self, chat_id):
        """Send recent log lines"""
        if not LOG_FILE.exists():
            await self.send_message(chat_id, "No logs yet.")
            return
        
        lines = LOG_FILE.read_text().splitlines()[-20:]
        await self.send_message(chat_id, "\n".join(lines))
    
    async def run(self):
        """Main bot loop"""
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
    """Main entry point"""
    if not ENABLE_TELEGRAM:
        print("Bot disabled.")
        return
    
    if not TOKEN:
        print("BALE_BOT_TOKEN not set.")
        return
    
    # Verify dl.py exists
    if not DL_SCRIPT.exists():
        print(f"Error: {DL_SCRIPT} not found!")
        return
    
    bot = BaleBot(TOKEN, ALLOWED_CHAT_ID)
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
