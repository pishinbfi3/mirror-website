"""Main bot handler for processing messages and sending responses."""

import requests
import json
import time
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime
import traceback

from .config import BotConfig
from .executor import CommandExecutor
from .security import CommandSecurity


class BaleBotHandler:
    """Handles Bale bot API interactions and command processing."""
    
    def __init__(self, config: BotConfig):
        self.config = config
        self.executor = CommandExecutor(timeout=config.timeout_seconds)
        self.base_url = f"{config.api_base_url}/bot{config.bot_token}"
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Bale-SSH-Bot/1.0",
            "Accept": "application/json"
        })
    
    def get_updates(self, offset: Optional[int] = None) -> List[Dict[str, Any]]:
        """Fetch updates from Bale API."""
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
                
        except requests.exceptions.RequestException as e:
            self._log_error(f"Request failed: {e}")
            return []
        except json.JSONDecodeError as e:
            self._log_error(f"JSON decode error: {e}")
            return []
    
    def send_message(self, text: str, reply_to_message_id: Optional[int] = None) -> bool:
        """Send a message to the configured chat."""
        url = f"{self.base_url}/sendMessage"
        
        # Split long messages
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
                data = response.json()
                
                if not data.get("ok"):
                    self._log_error(f"Failed to send message: {data}")
                    # Retry without markdown
                    payload["parse_mode"] = None
                    response = self.session.post(url, json=payload, timeout=30)
                    
            except Exception as e:
                self._log_error(f"Error sending message: {e}")
                return False
        
        return True
    
    def send_file(self, file_path: str, caption: Optional[str] = None) -> bool:
        """Send a file to the configured chat."""
        url = f"{self.base_url}/sendDocument"
        
        try:
            with open(file_path, 'rb') as f:
                files = {"document": f}
                data = {"chat_id": self.config.chat_id}
                
                if caption:
                    data["caption"] = caption
                
                response = self.session.post(url, files=files, data=data, timeout=60)
                response.raise_for_status()
                
                return response.json().get("ok", False)
                
        except Exception as e:
            self._log_error(f"Error sending file: {e}")
            return False
    
        # در متد process_command، بخش validation رو اینطور تغییر بده:
        
        def process_command(self, command: str) -> Tuple[str, Optional[str]]:
            """Process a shell command and return response and optional file path."""
            # Handle special commands
            if command.startswith('/'):
                return self._handle_bot_command(command), None
            
            # NO VALIDATION - ALL COMMANDS ALLOWED
            is_valid, error = CommandSecurity.validate_command(command)
            
            if not is_valid:
                return f"❌ Command rejected: {error}", None
            
            # Minimal sanitization
            sanitized = CommandSecurity.sanitize_command(command)
            
            # Send typing indicator
            self.send_chat_action("typing")
            
            # Execute command
            exit_code, stdout, stderr, exec_time = self.executor.execute(sanitized)
            
            # Format response
            response = self._format_command_response(
                command, exit_code, stdout, stderr, exec_time
            )
            
            # If output is too large, save to file
            file_path = None
            if len(response) > self.config.max_message_length:
                file_path = self._save_output_to_file(command, stdout, stderr)
                response = f"📁 Output saved to file (too large for message)\n"
                response += f"Command: `{command}`\n"
                response += f"Exit code: {exit_code}\n"
                response += f"Time: {exec_time:.2f}s"
            
            return response, file_path
        def send_chat_action(self, action: str = "typing") -> bool:
            """Send chat action indicator."""
            url = f"{self.base_url}/sendChatAction"
            payload = {
                "chat_id": self.config.chat_id,
                "action": action
            }

            try:
                response = self.session.post(url, json=payload, timeout=10)
                return response.json().get("ok", False)
            except Exception:
                return False

        def get_offset(self) -> int:
            """Read last update offset from file."""
            try:
                with open(self.config.update_offset_file, 'r') as f:
                    return int(f.read().strip())
            except (FileNotFoundError, ValueError):
                return 0

        def save_offset(self, offset: int):
            """Save last update offset to file."""
            try:
                with open(self.config.update_offset_file, 'w') as f:
                    f.write(str(offset))
            except Exception as e:
                self._log_error(f"Failed to save offset: {e}")

    def _handle_bot_command(self, command: str) -> str:
        """Handle bot-specific commands."""
        cmd_parts = command.lower().split()
        base_cmd = cmd_parts[0]

        commands_help = {
            "/start": "🚀 **Welcome to Bale SSH Bot - UNRESTRICTED VERSION**\n\n"
                     "⚠️ **WARNING:** This bot has NO SECURITY RESTRICTIONS!\n"
                     "ALL commands will be executed.\n\n"
                     "Commands:\n"
                     "/help - Show this help\n"
                     "/status - Show bot status\n"
                     "/ping - Check connectivity\n"
                     "/env - Show environment variables\n"
                     "/shell - Interactive shell mode info\n\n"
                     "**Send any command to execute it directly!**",

            "/help": "**🔓 UNRESTRICTED BOT - Available Commands:**\n\n"
                    "/start - Start bot\n"
                    "/help - Show this help\n"
                    "/status - Show system status\n"
                    "/ping - Test connectivity\n"
                    "/env - Show all environment variables\n"
                    "/shell - Interactive shell tips\n\n"
                    "**💻 ANY shell command is allowed:**\n"
                    "• Full bash syntax supported\n"
                    "• Multi-line commands with heredoc\n"
                    "• Pipes, redirects, command substitution\n"
                    "• Background processes (use with caution)\n\n"
                    "**Examples:**\n"
                    "`ls -la`\n"
                    "`find / -name '*.py' 2>/dev/null | head -20`\n"
                    "`python3 -c 'print(\"Hello\")'`\n"
                    "`curl -s https://api.github.com/repos/torvalds/linux`\n"
                    "`cat > /tmp/test.txt << EOF\\nline1\\nline2\\nEOF`",

            "/status": self._get_system_status(),

            "/ping": "🏓 Pong! Bot is running (UNRESTRICTED MODE).\n"
                    f"Timestamp: {datetime.now().isoformat()}",

            "/env": self._get_all_env_vars(),

            "/shell": "**🐚 Interactive Shell Tips:**\n\n"
                     "Since each command runs in a fresh session, for multi-step tasks:\n\n"
                     "1️⃣ Use semicolons: `cd /tmp; ls -la; pwd`\n"
                     "2️⃣ Use subshells: `(cd /tmp && ls -la)`\n"
                     "3️⃣ Save state to files: `echo 'data' > /tmp/state.txt`\n"
                     "4️⃣ Use environment: `export FOO=bar; echo $FOO`\n"
                     "5️⃣ Here-documents for multi-line input:\n"
                     "```\n"
                     "cat > /tmp/script.sh << 'SCRIPT'\n"
                     "#!/bin/bash\n"
                     "echo 'Hello'\n"
                     "ls -la\n"
                     "SCRIPT\n"
                     "chmod +x /tmp/script.sh && /tmp/script.sh\n"
                     "```",
        }

        return commands_help.get(base_cmd, f"Unknown command: {base_cmd}\nType /help for available commands.")
    
    def _get_all_env_vars(self) -> str:
        """Get ALL environment variables (no filtering)."""
        import os
        
        lines = ["**🌍 All Environment Variables:**"]
        
        # Sort and display all env vars
        for key, value in sorted(os.environ.items()):
            # Mask sensitive values partially
            if any(sensitive in key.upper() for sensitive in ['TOKEN', 'KEY', 'SECRET', 'PASSWORD', 'PASS']):
                if value:
                    value = value[:4] + "..." + value[-4:] if len(value) > 8 else "***"
            else:
                # Truncate very long values
                if len(value) > 200:
                    value = value[:197] + "..."
            
            lines.append(f"• `{key}` = `{value}`")
        
        # Split into chunks if too large
        return "\n".join(lines)
    
    def _get_system_status(self) -> str:
        """Get system status information."""
        import platform
        
        status_lines = [
            "**System Status**",
            f"🖥️ Hostname: `{platform.node()}`",
            f"🐍 Python: `{platform.python_version()}`",
            f"💻 OS: `{platform.system()} {platform.release()}`",
            f"🏗️ Arch: `{platform.machine()}`",
            f"📅 Time: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`",
        ]
        
        # Get memory info
        try:
            import subprocess
            mem = subprocess.run(['free', '-h'], capture_output=True, text=True, timeout=5)
            if mem.returncode == 0:
                mem_line = mem.stdout.split('\n')[1]
                status_lines.append(f"💾 Memory: `{mem_line.split()[1]}` / `{mem_line.split()[2]}`")
        except Exception:
            pass
        
        # Get disk info
        try:
            import shutil
            usage = shutil.disk_usage('.')
            status_lines.append(f"💿 Disk free: `{usage.free // (2**30)}GB`")
        except Exception:
            pass
        
        return "\n".join(status_lines)
    
    def _get_safe_env_vars(self) -> str:
        """Get safe environment variables."""
        import os
        
        safe_vars = [
            "PATH", "HOME", "USER", "SHELL", "PWD", "LANG",
            "PYTHON_VERSION", "NODE_VERSION", "JAVA_HOME",
            "GITHUB_WORKFLOW", "GITHUB_ACTION", "GITHUB_RUN_ID",
            "RUNNER_OS", "RUNNER_ARCH"
        ]
        
        lines = ["**Safe Environment Variables:**"]
        for var in safe_vars:
            value = os.environ.get(var)
            if value:
                # Truncate long values
                if len(value) > 100:
                    value = value[:97] + "..."
                lines.append(f"• `{var}` = `{value}`")
        
        return "\n".join(lines)
    
    def _format_command_response(self, command: str, exit_code: int, 
                                 stdout: str, stderr: str, exec_time: float) -> str:
        """Format command execution response."""
        status = "✅" if exit_code == 0 else "❌"
        
        lines = [
            f"{status} **Command executed**",
            f"```bash",
            f"$ {command}",
            f"```",
            "",
            f"📊 Exit Code: `{exit_code}`",
            f"⏱️ Time: `{exec_time:.2f}s`",
        ]
        
        if stdout:
            lines.extend(["", "**📤 STDOUT:**", "```", stdout.rstrip(), "```"])
        
        if stderr:
            lines.extend(["", "**⚠️ STDERR:**", "```", stderr.rstrip(), "```"])
        
        if not stdout and not stderr:
            lines.extend(["", "*(no output)*"])
        
        return "\n".join(lines)
    
    def _save_output_to_file(self, command: str, stdout: str, stderr: str) -> str:
        """Save command output to a file and return the path."""
        import tempfile
        
        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.txt',
            prefix=f"bale_output_{datetime.now().strftime('%Y%m%d_%H%M%S')}_",
            delete=False
        ) as f:
            f.write(f"Command: {command}\n")
            f.write(f"Timestamp: {datetime.now().isoformat()}\n")
            f.write("=" * 60 + "\n\n")
            f.write("STDOUT:\n")
            f.write("=" * 60 + "\n")
            f.write(stdout if stdout else "(empty)\n")
            f.write("\n" + "=" * 60 + "\n\n")
            f.write("STDERR:\n")
            f.write("=" * 60 + "\n")
            f.write(stderr if stderr else "(empty)\n")
            
            return f.name
    
    def _split_message(self, text: str, max_len: int = 4000) -> List[str]:
        """Split a long message into chunks."""
        if len(text) <= max_len:
            return [text]
        
        chunks = []
        lines = text.split('\n')
        current_chunk = ""
        
        for line in lines:
            if len(current_chunk) + len(line) + 1 > max_len:
                if current_chunk:
                    chunks.append(current_chunk.rstrip())
                    current_chunk = ""
                
                # If a single line is too long, split it
                if len(line) > max_len:
                    for i in range(0, len(line), max_len - 100):
                        chunks.append(line[i:i + max_len - 100] + "...")
                else:
                    current_chunk = line
            else:
                if current_chunk:
                    current_chunk += "\n" + line
                else:
                    current_chunk = line
        
        if current_chunk:
            chunks.append(current_chunk)
        
        return chunks
    
    def _log_error(self, message: str):
        """Log error message to file."""
        try:
            with open(self.config.log_file, 'a') as f:
                f.write(f"{datetime.now().isoformat()} - {message}\n")
        except Exception:
            pass
