"""Main bot handler for processing messages, files, and persistent shell commands."""

import requests
import json
import time
import os
import tempfile
import zipfile
import shutil
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime
import traceback

from .config import BotConfig
from .executor import PersistentShell
from .security import CommandSecurity


class BaleBotHandler:
    """Handles Bale bot API interactions, file transfers, and persistent commands."""

    def __init__(self, config: BotConfig):
        self.config = config
        self.shell = PersistentShell(timeout=config.timeout_seconds)
        self.base_url = f"{config.api_base_url}/bot{config.bot_token}"
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Bale-SSH-Bot/1.0",
            "Accept": "application/json"
        })
        self.pending_edit = {}  # {user_id: {"filepath": str, "step": "awaiting_content"}}

    # ---------- Existing API methods (get_updates, send_message, etc.) remain unchanged ----------
    def get_updates(self, offset: Optional[int] = None) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/getUpdates"
        params = {"timeout": 30, "limit": 10}
        if offset:
            params["offset"] = offset
        try:
            response = self.session.get(url, params=params, timeout=35)
            response.raise_for_status()
            data = response.json()
            if data.get("ok"):
                return data.get("result", [])
            else:
                self._log_error(f"API error: {data}")
                return []
        except Exception as e:
            self._log_error(f"Request failed: {e}")
            return []

    def send_message(self, text: str, reply_to_message_id: Optional[int] = None) -> bool:
        url = f"{self.base_url}/sendMessage"
        messages = self._split_message(text)
        for msg in messages:
            payload = {
                "chat_id": self.config.chat_id,
                "text": msg,
                "parse_mode": "Markdown"
            }
            if reply_to_message_id and msg == messages[0]:
                payload["reply_to_message_id"] = reply_to_message_id
            try:
                response = self.session.post(url, json=payload, timeout=30)
                response.raise_for_status()
                if not response.json().get("ok"):
                    payload["parse_mode"] = None
                    self.session.post(url, json=payload, timeout=30)
            except Exception as e:
                self._log_error(f"Error sending message: {e}")
                return False
        return True

    def send_file(self, file_path: str, caption: Optional[str] = None) -> bool:
        url = f"{self.base_url}/sendDocument"
        try:
            with open(file_path, 'rb') as f:
                files = {"document": f}
                data = {"chat_id": self.config.chat_id}
                if caption:
                    data["caption"] = caption
                response = self.session.post(url, files=files, data=data, timeout=60)
                return response.json().get("ok", False)
        except Exception as e:
            self._log_error(f"Error sending file: {e}")
            return False

    def send_chat_action(self, action: str = "typing") -> bool:
        url = f"{self.base_url}/sendChatAction"
        payload = {"chat_id": self.config.chat_id, "action": action}
        try:
            response = self.session.post(url, json=payload, timeout=10)
            return response.json().get("ok", False)
        except Exception:
            return False

    def get_offset(self) -> int:
        try:
            with open(self.config.update_offset_file, 'r') as f:
                return int(f.read().strip())
        except (FileNotFoundError, ValueError):
            return 0

    def save_offset(self, offset: int):
        try:
            with open(self.config.update_offset_file, 'w') as f:
                f.write(str(offset))
        except Exception as e:
            self._log_error(f"Failed to save offset: {e}")

    # ---------- New file handling methods ----------
    def download_file(self, file_id: str) -> Optional[str]:
        """Download a file from Bale servers and return local path."""
        # Get file path
        url = f"{self.base_url}/getFile"
        try:
            resp = self.session.get(url, params={"file_id": file_id}, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok"):
                return None
            file_path = data["result"]["file_path"]
            download_url = f"{self.config.api_base_url}/file/bot{self.config.bot_token}/{file_path}"
            # Download
            local_path = f"/tmp/bale_download_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file_id[:8]}"
            r = self.session.get(download_url, stream=True)
            with open(local_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            return local_path
        except Exception as e:
            self._log_error(f"File download error: {e}")
            return None

    def split_and_send_file(self, file_path: str, original_name: str) -> bool:
        """If file > 10MB, zip and split into 9MB chunks, send each chunk."""
        MAX_SIZE = 10 * 1024 * 1024  # 10 MB
        CHUNK_SIZE = 9 * 1024 * 1024  # 9 MB per part

        file_size = os.path.getsize(file_path)
        if file_size <= MAX_SIZE:
            return self.send_file(file_path, f"📁 {original_name} ({file_size//1024} KB)")

        # Create a zip archive
        zip_name = f"/tmp/{original_name}.zip"
        with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.write(file_path, arcname=original_name)

        # Split zip into chunks
        part_num = 1
        with open(zip_name, 'rb') as f_in:
            while True:
                chunk = f_in.read(CHUNK_SIZE)
                if not chunk:
                    break
                part_path = f"/tmp/{original_name}.zip.part{part_num:03d}"
                with open(part_path, 'wb') as f_out:
                    f_out.write(chunk)
                # Send part
                caption = f"📦 {original_name} (part {part_num}) – combine with: cat {original_name}.zip.part* > {original_name}.zip && unzip {original_name}.zip"
                if not self.send_file(part_path, caption):
                    return False
                os.unlink(part_path)
                part_num += 1
        os.unlink(zip_name)
        return True

    def handle_document(self, message: Dict[str, Any]) -> str:
        """Process a received document: save to current directory of persistent shell."""
        document = message.get("document")
        if not document:
            return "❌ No document found."
        file_id = document.get("file_id")
        file_name = document.get("file_name", "uploaded_file")
        local_path = self.download_file(file_id)
        if not local_path:
            return "❌ Failed to download file."
        # Determine destination path (current working directory of shell)
        # We'll get cwd by executing 'pwd' in the persistent shell
        exit_code, stdout, stderr, _ = self.shell.execute("pwd")
        if exit_code != 0:
            dest_dir = "/tmp"
        else:
            dest_dir = stdout.strip()
        dest_path = os.path.join(dest_dir, file_name)
        shutil.move(local_path, dest_path)
        return f"✅ File saved to `{dest_path}` ({os.path.getsize(dest_path)} bytes)"

    # ---------- Command processing ----------
    def process_command(self, command: str) -> Tuple[str, Optional[str]]:
        """Process a shell command or bot command."""
        if command.startswith('/'):
            return self._handle_bot_command(command), None

        # Normal shell command via persistent shell
        self.send_chat_action("typing")
        exit_code, stdout, stderr, exec_time = self.shell.execute(command)
        response = self._format_command_response(command, exit_code, stdout, stderr, exec_time)
        file_path = None
        if len(response) > self.config.max_message_length:
            file_path = self._save_output_to_file(command, stdout, stderr)
            response = f"📁 Output saved to file (too large for message)\nCommand: `{command}`\nExit: {exit_code}\nTime: {exec_time:.2f}s"
        return response, file_path

    def _handle_bot_command(self, command: str) -> str:
        cmd_parts = command.lower().split()
        base_cmd = cmd_parts[0]

        # Built-in commands
        if base_cmd == "/stop":
            return "🛑 Stopping bot..."
        elif base_cmd == "/download":
            if len(cmd_parts) < 2:
                return "❌ Usage: `/download <filepath>`"
            filepath = cmd_parts[1]
            if not os.path.exists(filepath):
                return f"❌ File not found: {filepath}"
            # Send file with auto-splitting
            if self.split_and_send_file(filepath, os.path.basename(filepath)):
                return f"✅ Sending `{filepath}` (split if >10MB)"
            else:
                return f"❌ Failed to send file."
        elif base_cmd == "/upload":
            return "📤 Please send a document (file) to upload it to the current directory."
        elif base_cmd == "/edit":
            if len(cmd_parts) < 2:
                return "❌ Usage: `/edit <filepath>`\nI will send current content, then you reply with new content using `/save`."
            filepath = cmd_parts[1]
            if not os.path.exists(filepath):
                return f"❌ File not found: {filepath}"
            try:
                with open(filepath, 'r') as f:
                    content = f.read()
                # Send content in a code block
                msg = f"📝 Editing `{filepath}`\nSend `/save {filepath}` with the new content (in a single message).\nCurrent content:\n```\n{content[:3000]}\n```"
                if len(content) > 3000:
                    msg += f"\n... (truncated, {len(content)} total chars)"
                return msg
            except Exception as e:
                return f"❌ Cannot read file: {e}"
        elif base_cmd == "/save":
            if len(cmd_parts) < 2:
                return "❌ Usage: `/save <filepath>` followed by the new content (in the same message or next message)."
            filepath = cmd_parts[1]
            # Extract content from the rest of the message
            content = ' '.join(cmd_parts[2:]) if len(cmd_parts) > 2 else ""
            if not content:
                return "❌ Please provide the new content after the command."
            try:
                with open(filepath, 'w') as f:
                    f.write(content)
                return f"✅ Saved to `{filepath}`"
            except Exception as e:
                return f"❌ Write error: {e}"
        elif base_cmd == "/cd":
            if len(cmd_parts) < 2:
                return "❌ Usage: `/cd <directory>`"
            # Change directory in persistent shell
            self.shell.execute(f"cd {cmd_parts[1]}")
            # Verify
            _, pwd, _, _ = self.shell.execute("pwd")
            return f"📂 Current directory: `{pwd.strip()}`"
        elif base_cmd == "/pwd":
            _, pwd, _, _ = self.shell.execute("pwd")
            return f"📂 `{pwd.strip()}`"
        elif base_cmd == "/info":
            return self._get_system_info()
        elif base_cmd == "/ps":
            _, out, _, _ = self.shell.execute("ps aux --sort=-%cpu | head -20")
            return f"**🔄 Top processes**\n```\n{out[:3500]}\n```"
        elif base_cmd == "/df":
            _, out, _, _ = self.shell.execute("df -h")
            return f"**💾 Disk usage**\n```\n{out}\n```"
        elif base_cmd == "/netstat":
            _, out, _, _ = self.shell.execute("ss -tulpn 2>/dev/null || netstat -tulpn 2>/dev/null")
            return f"**🌐 Open ports**\n```\n{out[:3500]}\n```"
        elif base_cmd == "/uptime":
            _, out, _, _ = self.shell.execute("uptime")
            return f"⏱️ `{out.strip()}`"
        elif base_cmd == "/mem":
            _, out, _, _ = self.shell.execute("free -h")
            return f"**🧠 Memory**\n```\n{out}\n```"
        else:
            # Default help
            return self._get_help_text()

    def _get_help_text(self) -> str:
        return """**🔓 UNRESTRICTED BOT – Enhanced Commands**

**Shell:** Any command runs in persistent session (cd, env vars preserved).
**Files:**
• `/download <path>` – download file (auto-split >10MB)
• `/upload` – send a document to upload to current dir
• `/edit <file>` – view file content
• `/save <file> <content>` – save/replace file
**Session:**
• `/cd <dir>` – change directory
• `/pwd` – show current dir
• `/stop` – stop bot
**Info:**
• `/info` – detailed system info
• `/ps` – top processes
• `/df` – disk usage
• `/netstat` – open ports
• `/uptime` – system uptime
• `/mem` – memory usage
• `/help` – this help"""

    def _get_system_info(self) -> str:
        """Return extensive system information."""
        info = []
        # Hostname, OS, kernel
        _, uname, _, _ = self.shell.execute("uname -a")
        info.append(f"🖥️ **System:** `{uname.strip()}`")
        _, cpu, _, _ = self.shell.execute("nproc")
        info.append(f"🧠 **CPU cores:** `{cpu.strip()}`")
        _, mem, _, _ = self.shell.execute("free -h | grep Mem")
        if mem:
            parts = mem.split()
            info.append(f"💾 **RAM:** total `{parts[1]}`, used `{parts[2]}`, free `{parts[3]}`")
        _, disk, _, _ = self.shell.execute("df -h / | tail -1")
        if disk:
            parts = disk.split()
            info.append(f"💿 **Disk (/):** `{parts[3]}` free of `{parts[1]}`")
        _, load, _, _ = self.shell.execute("uptime | awk -F 'load average:' '{print $2}'")
        info.append(f"📈 **Load avg:** `{load.strip()}`")
        _, users, _, _ = self.shell.execute("who | wc -l")
        info.append(f"👥 **Logged users:** `{users.strip()}`")
        return "\n".join(info)

    # ---------- Helper methods (existing) ----------
    def _format_command_response(self, command: str, exit_code: int, stdout: str, stderr: str, exec_time: float) -> str:
        status = "✅" if exit_code == 0 else "❌"
        lines = [f"{status} **Command executed**", f"```bash\n$ {command}\n```", "", f"📊 Exit Code: `{exit_code}`", f"⏱️ Time: `{exec_time:.2f}s`"]
        if stdout:
            lines.extend(["", "**📤 STDOUT:**", "```", stdout.rstrip(), "```"])
        if stderr:
            lines.extend(["", "**⚠️ STDERR:**", "```", stderr.rstrip(), "```"])
        if not stdout and not stderr:
            lines.extend(["", "*(no output)*"])
        return "\n".join(lines)

    def _save_output_to_file(self, command: str, stdout: str, stderr: str) -> str:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', prefix=f"bale_output_{datetime.now().strftime('%Y%m%d_%H%M%S')}_", delete=False) as f:
            f.write(f"Command: {command}\nTimestamp: {datetime.now().isoformat()}\n{'='*60}\nSTDOUT:\n{'='*60}\n{stdout if stdout else '(empty)'}\n\n{'='*60}\nSTDERR:\n{'='*60}\n{stderr if stderr else '(empty)'}")
            return f.name

    def _split_message(self, text: str, max_len: int = 4000) -> List[str]:
        if len(text) <= max_len:
            return [text]
        chunks = []
        lines = text.split('\n')
        current = ""
        for line in lines:
            if len(current) + len(line) + 1 > max_len:
                chunks.append(current.rstrip())
                current = line
            else:
                current += ("\n" + line) if current else line
        if current:
            chunks.append(current)
        return chunks

    def _log_error(self, message: str):
        try:
            with open(self.config.log_file, 'a') as f:
                f.write(f"{datetime.now().isoformat()} - {message}\n")
        except Exception:
            pass

    def close(self):
        """Clean up persistent shell."""
        self.shell.close()
