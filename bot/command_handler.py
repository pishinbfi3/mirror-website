"""Command registry and processing logic."""

import os
import shutil
import tempfile
from typing import Dict, Callable, Awaitable, Tuple, Optional

from .config import BotConfig
from .executor import CommandExecutor
from .process_manager import ProcessManager
from .api_client import BaleAPIClient
from .logger import get_logger
from .models import Message

logger = get_logger(__name__)


class CommandHandler:
    """Handles all bot commands and file uploads."""

    def __init__(
        self,
        config: BotConfig,
        executor: CommandExecutor,
        process_manager: ProcessManager,
        api_client: BaleAPIClient,
    ):
        self.config = config
        self.executor = executor
        self.pm = process_manager
        self.api = api_client
        self._commands: Dict[str, Callable[[str, Message], Awaitable[str]]] = {}
        self._register_commands()

    def _register_commands(self):
        """Register all built-in commands with their handlers."""
        # Basic shell integration is handled separately (non‑/ commands)
        # But we also support /commands
        self._commands["/start"] = self._cmd_help
        self._commands["/help"] = self._cmd_help
        self._commands["/cd"] = self._cmd_cd
        self._commands["/pwd"] = self._cmd_pwd
        self._commands["/download"] = self._cmd_download
        self._commands["/upload"] = self._cmd_upload
        self._commands["/edit"] = self._cmd_edit
        self._commands["/save"] = self._cmd_save
        self._commands["/jobs"] = self._cmd_jobs
        self._commands["/kill"] = self._cmd_kill
        self._commands["/output"] = self._cmd_output
        self._commands["/bg"] = self._cmd_bg
        self._commands["/background"] = self._cmd_bg
        self._commands["/info"] = self._cmd_info
        self._commands["/ps"] = self._cmd_ps
        self._commands["/df"] = self._cmd_df
        self._commands["/netstat"] = self._cmd_netstat
        self._commands["/uptime"] = self._cmd_uptime
        self._commands["/mem"] = self._cmd_mem

    async def handle_message(self, message: Message) -> Tuple[str, Optional[str]]:
        """
        Process a message: document upload or text command.
        Returns (response_text, optional_file_path_to_send).
        """
        # Document upload
        if message.document:
            return await self._handle_document(message)

        # Text message
        text = (message.text or message.caption or "").strip()
        if not text:
            return "⚠️ Empty message", None

        # Bot command
        if text.startswith("/"):
            cmd_name = text.split()[0].lower()
            handler = self._commands.get(cmd_name)
            if handler:
                response = await handler(text, message)
                return response, None
            else:
                return f"❌ Unknown command: {cmd_name}\nType /help", None

        # Otherwise treat as shell command (with optional background)
        return await self._run_shell_command(text)

    async def _run_shell_command(self, command: str) -> Tuple[str, Optional[str]]:
        """Run a shell command, possibly in background."""
        cmd = command.strip()
        background = False
        if cmd.endswith(" &"):
            background = True
            cmd = cmd[:-2].strip()
        elif cmd.startswith("!"):
            background = True
            cmd = cmd[1:].strip()

        if background:
            job_id = await self.pm.submit(cmd)
            return (
                f"🔄 Background job `{job_id}` started.\n"
                f"Use `/jobs` to see status, `/kill {job_id}` to stop.",
                None,
            )

        # Synchronous execution
        await self.api.send_chat_action(self.config.chat_id, "typing")
        exit_code, stdout, stderr, exec_time = await self.executor.execute(cmd)
        response = self._format_cmd_response(cmd, exit_code, stdout, stderr, exec_time)
        file_path = None
        if len(response) > self.config.max_message_length:
            file_path = self._save_output_temp(cmd, stdout, stderr)
            response = f"📁 Output saved to file (too large)\nCommand: `{cmd}`\nExit: {exit_code}\nTime: {exec_time:.2f}s"
        return response, file_path

    # ---------- Built-in command handlers ----------
    async def _cmd_help(self, _cmd: str, _msg: Message) -> str:
        return """**🔓 Bale SSH Bot – Help**
**Shell commands:** Any command (cd, ls, etc.) stateful.
**Background:** Append `&` or start with `!` → `!sleep 10 &`
**Files:** `/download <path>` , `/upload` (send document), `/edit`, `/save`
**Session:** `/cd`, `/pwd`, `/stop` (saves snapshot)
**Processes:** `/bg <cmd>`, `/jobs`, `/kill <id>`, `/output <id>`
**System:** `/info`, `/ps`, `/df`, `/netstat`, `/uptime`, `/mem`"""

    async def _cmd_cd(self, cmd: str, _msg: Message) -> str:
        parts = cmd.split()
        if len(parts) < 2:
            return "❌ Usage: `/cd <directory>`"
        target = parts[1]
        if self.executor.set_directory(target):
            return f"📂 Changed to `{self.executor.get_directory()}`"
        return f"❌ Directory not found: {target}"

    async def _cmd_pwd(self, _cmd: str, _msg: Message) -> str:
        return f"📂 `{self.executor.get_directory()}`"

    async def _cmd_download(self, cmd: str, _msg: Message) -> str:
        parts = cmd.split()
        if len(parts) < 2:
            return "❌ Usage: `/download <path>`"
        path = parts[1]
        if not os.path.exists(path):
            return f"❌ Not found: {path}"
        if os.path.isdir(path):
            zip_path = f"/tmp/{os.path.basename(path)}.zip"
            shutil.make_archive(zip_path.replace(".zip", ""), "zip", path)
            success = await self._send_large_file(zip_path, os.path.basename(zip_path))
            os.unlink(zip_path)
            return "✅ Sending directory as ZIP" if success else "❌ Failed to send"
        else:
            success = await self._send_large_file(path, os.path.basename(path))
            return f"✅ Sending `{path}`" if success else "❌ Failed to send"

    async def _cmd_upload(self, _cmd: str, _msg: Message) -> str:
        return "📤 Send a document (file) to upload it to the current directory."

    async def _cmd_edit(self, cmd: str, _msg: Message) -> str:
        parts = cmd.split()
        if len(parts) < 2:
            return "❌ Usage: `/edit <filepath>`"
        path = parts[1]
        if not os.path.exists(path):
            return f"❌ File not found: {path}"
        try:
            with open(path, "r") as f:
                content = f.read()
            snippet = content[:3000]
            return f"📝 Editing `{path}`\nSend `/save {path} <new content>`\nCurrent content:\n```\n{snippet}\n```"
        except Exception as e:
            return f"❌ Cannot read: {e}"

    async def _cmd_save(self, cmd: str, _msg: Message) -> str:
        parts = cmd.split(maxsplit=2)
        if len(parts) < 3:
            return "❌ Usage: `/save <filepath> <content>`"
        path = parts[1]
        content = parts[2]
        try:
            with open(path, "w") as f:
                f.write(content)
            return f"✅ Saved to `{path}`"
        except Exception as e:
            return f"❌ Write error: {e}"

    async def _cmd_jobs(self, _cmd: str, _msg: Message) -> str:
        jobs = self.pm.list_jobs(limit=15)
        if not jobs:
            return "📭 No jobs."
        lines = ["**📋 Recent Jobs:**"]
        for j in jobs:
            runtime = (j.finished_at or j.created_at) - j.created_at
            lines.append(f"`{j.job_id}` | {j.status} | {runtime:.1f}s | {j.command[:50]}")
        return "\n".join(lines)

    async def _cmd_kill(self, cmd: str, _msg: Message) -> str:
        parts = cmd.split()
        if len(parts) < 2:
            return "❌ Usage: `/kill <job_id>`"
        job_id = parts[1]
        if await self.pm.kill(job_id):
            return f"✅ Killed job `{job_id}`"
        return f"❌ Job `{job_id}` not running or not found."

    async def _cmd_output(self, cmd: str, _msg: Message) -> str:
        parts = cmd.split()
        if len(parts) < 2:
            return "❌ Usage: `/output <job_id>`"
        out = await self.pm.get_output(parts[1])
        return out if out else "❌ Job not found."

    async def _cmd_bg(self, cmd: str, _msg: Message) -> str:
        parts = cmd.split(maxsplit=1)
        if len(parts) < 2:
            return "❌ Usage: `/bg <command>`"
        job_id = await self.pm.submit(parts[1])
        return f"🆔 Job `{job_id}` started in background."

    async def _cmd_info(self, _cmd: str, _msg: Message) -> str:
        lines = []
        # Get system info via executor
        _, uname, _, _ = await self.executor.execute("uname -a")
        lines.append(f"🖥️ **System:** `{uname.strip()}`")
        _, cpu, _, _ = await self.executor.execute("nproc")
        lines.append(f"🧠 **CPU cores:** `{cpu.strip()}`")
        _, mem, _, _ = await self.executor.execute("free -h | grep Mem")
        if mem:
            parts = mem.split()
            lines.append(f"💾 **RAM:** total {parts[1]}, used {parts[2]}, free {parts[3]}")
        _, disk, _, _ = await self.executor.execute("df -h / | tail -1")
        if disk:
            parts = disk.split()
            lines.append(f"💿 **Disk (/):** {parts[3]} free of {parts[1]}")
        return "\n".join(lines)

    async def _cmd_ps(self, _cmd: str, _msg: Message) -> str:
        _, out, _, _ = await self.executor.execute("ps aux --sort=-%cpu | head -20")
        return f"**🔄 Top processes**\n```\n{out[:3500]}\n```"

    async def _cmd_df(self, _cmd: str, _msg: Message) -> str:
        _, out, _, _ = await self.executor.execute("df -h")
        return f"**💾 Disk usage**\n```\n{out}\n```"

    async def _cmd_netstat(self, _cmd: str, _msg: Message) -> str:
        _, out, _, _ = await self.executor.execute("ss -tulpn 2>/dev/null || netstat -tulpn 2>/dev/null")
        return f"**🌐 Open ports**\n```\n{out[:3500]}\n```"

    async def _cmd_uptime(self, _cmd: str, _msg: Message) -> str:
        _, out, _, _ = await self.executor.execute("uptime")
        return f"⏱️ `{out.strip()}`"

    async def _cmd_mem(self, _cmd: str, _msg: Message) -> str:
        _, out, _, _ = await self.executor.execute("free -h")
        return f"**🧠 Memory**\n```\n{out}\n```"

    # ---------- Helpers ----------
    async def _handle_document(self, message: Message) -> Tuple[str, Optional[str]]:
        doc = message.document
        file_id = doc.file_id
        file_name = doc.file_name or "uploaded_file"
        download_url = await self.api.get_file(file_id)
        # Download file asynchronously
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(download_url) as resp:
                local_path = f"/tmp/bale_dl_{file_name}"
                with open(local_path, "wb") as f:
                    while True:
                        chunk = await resp.content.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)
        dest_path = os.path.join(self.executor.get_directory(), file_name)
        shutil.move(local_path, dest_path)
        return f"✅ File saved to `{dest_path}` ({os.path.getsize(dest_path)} bytes)", None

    async def _send_large_file(self, path: str, name: str) -> bool:
        """Send a file, splitting if >10 MiB."""
        MAX_SIZE = 10 * 1024 * 1024
        CHUNK = self.config.chunk_size
        size = os.path.getsize(path)
        if size <= MAX_SIZE:
            await self.api.send_document(self.config.chat_id, path, f"📁 {name}")
            return True
        # Split into parts
        total = (size + CHUNK - 1) // CHUNK
        with open(path, "rb") as f_in:
            for i in range(total):
                part_data = f_in.read(CHUNK)
                part_path = f"/tmp/{name}.part{i+1:03d}"
                with open(part_path, "wb") as f_out:
                    f_out.write(part_data)
                caption = f"📦 {name} part {i+1}/{total}\nCombine: `cat {name}.part* > {name}`"
                await self.api.send_document(self.config.chat_id, part_path, caption)
                os.unlink(part_path)
        return True

    def _format_cmd_response(
        self, cmd: str, exit_code: int, stdout: str, stderr: str, exec_time: float
    ) -> str:
        status = "✅" if exit_code == 0 else "❌"
        lines = [f"{status} **Command executed**", f"```bash\n$ {cmd}\n```", f"Exit: `{exit_code}` | Time: `{exec_time:.2f}s`"]
        if stdout:
            lines.extend(["", "📤 STDOUT:", "```", stdout.rstrip(), "```"])
        if stderr:
            lines.extend(["", "⚠️ STDERR:", "```", stderr.rstrip(), "```"])
        if not stdout and not stderr:
            lines.append("*(no output)*")
        return "\n".join(lines)

    def _save_output_temp(self, cmd: str, stdout: str, stderr: str) -> str:
        fd, path = tempfile.mkstemp(suffix=".txt", prefix="bale_out_")
        with os.fdopen(fd, "w") as f:
            f.write(f"Command: {cmd}\n\nSTDOUT:\n{stdout}\n\nSTDERR:\n{stderr}")
        return path
