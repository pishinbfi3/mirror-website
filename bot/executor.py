"""Async command executor with persistent working directory."""

import asyncio
import os
import tempfile
from typing import Tuple, Optional

from .config import BotConfig
from .exceptions import CommandError
from .logger import get_logger

logger = get_logger(__name__)


class CommandExecutor:
    """Executes shell commands asynchronously, keeping cd state."""

    def __init__(self, config: BotConfig):
        self.config = config
        self.current_dir = os.getcwd()  # start at repo root
        self.env = os.environ.copy()
        self.env["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

    async def execute(
        self, command: str
    ) -> Tuple[int, str, str, float]:
        """
        Execute a command asynchronously.
        For `cd` command, update internal state without subprocess.
        Returns (exit_code, stdout, stderr, execution_time_seconds).
        """
        import time
        start = time.monotonic()
        cmd = command.strip()

        # Handle cd internally
        if cmd.startswith("cd "):
            return self._handle_cd(cmd, start)

        # Build final command with cd prefix to preserve state
        final_cmd = cmd
        if self.current_dir:
            safe_dir = self.current_dir.replace("'", "'\\''")
            final_cmd = f"cd '{safe_dir}' && {cmd}"

        # Run in thread pool (subprocess is blocking)
        loop = asyncio.get_running_loop()
        try:
            proc = await asyncio.create_subprocess_shell(
                final_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self.env,
                executable="/bin/bash",
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.config.command_timeout
            )
            exit_code = proc.returncode
            stdout_str = stdout.decode("utf-8", errors="replace")
            stderr_str = stderr.decode("utf-8", errors="replace")
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            exit_code = -1
            stdout_str = ""
            stderr_str = f"Command timed out after {self.config.command_timeout} seconds"
        except Exception as e:
            logger.exception("Command execution failed")
            exit_code = -1
            stdout_str = ""
            stderr_str = str(e)

        # Truncate if needed
        max_chars = self.config.max_output_chars
        if len(stdout_str) > max_chars:
            stdout_str = stdout_str[:max_chars] + "\n...[truncated]"
        if len(stderr_str) > max_chars:
            stderr_str = stderr_str[:max_chars] + "\n...[truncated]"

        exec_time = time.monotonic() - start
        self._log_command(cmd, exit_code, exec_time)
        return exit_code, stdout_str, stderr_str, exec_time

    def _handle_cd(self, command: str, start_time: float) -> Tuple[int, str, str, float]:
        """Change internal directory without subprocess."""
        target = command[3:].strip().strip("'\"")
        if not target:
            return 1, "", "cd: missing directory", 0.0

        if target.startswith("/"):
            new_dir = target
        else:
            new_dir = os.path.join(self.current_dir, target)
        new_dir = os.path.abspath(new_dir)

        if os.path.isdir(new_dir):
            self.current_dir = new_dir
            return 0, f"Changed directory to {self.current_dir}", "", 0.0
        else:
            return 1, "", f"cd: {target}: No such file or directory", 0.0

    def set_directory(self, path: str) -> bool:
        """Manually change current working directory."""
        if os.path.isdir(path):
            self.current_dir = os.path.abspath(path)
            return True
        test = os.path.join(self.current_dir, path)
        if os.path.isdir(test):
            self.current_dir = test
            return True
        return False

    def get_directory(self) -> str:
        return self.current_dir

    def _log_command(self, cmd: str, exit_code: int, exec_time: float) -> None:
        logger.debug(f"CMD: {cmd[:200]} | exit={exit_code} | time={exec_time:.2f}s")
