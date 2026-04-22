"""Command executor with manual state tracking (no persistent shell hang)."""

import subprocess
import os
import time
import tempfile
from typing import Tuple, Optional
from datetime import datetime


class CommandExecutor:
    """Executes commands with manual state tracking (cwd, env)."""

    def __init__(self, timeout: int = 300, max_output_size: int = 1_000_000):
        self.timeout = timeout
        self.max_output_size = max_output_size
        self.current_dir = os.getcwd()  # start in the repo root
        self.env = os.environ.copy()
        # Ensure PATH is safe
        self.env["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

    def execute(self, command: str) -> Tuple[int, str, str, float]:
        """
        Execute a command, optionally prefixing with cd to current_dir.
        Returns (exit_code, stdout, stderr, execution_time).
        """
        start_time = time.time()
        stdout = ""
        stderr = ""
        exit_code = -1

        # If command is not a cd command, and we have a current_dir set, prefix it
        final_command = command
        if not command.strip().startswith("cd ") and self.current_dir:
            # Escape single quotes in directory name
            safe_dir = self.current_dir.replace("'", "'\\''")
            final_command = f"cd '{safe_dir}' && {command}"

        try:
            # Use a temporary file to capture output (avoids pipe deadlocks)
            with tempfile.NamedTemporaryFile(mode='w+', suffix='.out', delete=False) as out_f, \
                 tempfile.NamedTemporaryFile(mode='w+', suffix='.err', delete=False) as err_f:

                proc = subprocess.Popen(
                    final_command,
                    shell=True,
                    executable='/bin/bash',
                    stdout=out_f,
                    stderr=err_f,
                    env=self.env,
                    cwd="/",  # we use explicit cd in command, so cwd doesn't matter
                    text=True
                )

                try:
                    exit_code = proc.wait(timeout=self.timeout)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                    stderr = f"Command timed out after {self.timeout} seconds"
                    exit_code = -1

                # Read output files
                with open(out_f.name, 'r') as f:
                    stdout = f.read(self.max_output_size)
                    if len(stdout) == self.max_output_size:
                        stdout += "\n... [Output truncated]"
                with open(err_f.name, 'r') as f:
                    stderr = f.read(self.max_output_size)
                    if len(stderr) == self.max_output_size:
                        stderr += "\n... [Output truncated]"

                os.unlink(out_f.name)
                os.unlink(err_f.name)

        except Exception as e:
            stderr = f"Execution error: {str(e)}"
            exit_code = -1

        # If the command was a cd command (successful), update current_dir
        if command.strip().startswith("cd ") and exit_code == 0:
            # Extract the target directory (handles quotes, ~, etc.)
            # We'll re-run a pwd to get the actual directory after cd
            pwd_proc = subprocess.run(
                "pwd", shell=True, capture_output=True, text=True, env=self.env, timeout=5
            )
            if pwd_proc.returncode == 0:
                self.current_dir = pwd_proc.stdout.strip()

        execution_time = time.time() - start_time
        self._save_output(command, exit_code, stdout, stderr, execution_time)
        return exit_code, stdout, stderr, execution_time

    def set_directory(self, path: str) -> bool:
        """Change the current working directory (manual state update)."""
        # Validate the directory exists
        test_cmd = f"cd '{path}' 2>/dev/null && pwd"
        proc = subprocess.run(test_cmd, shell=True, capture_output=True, text=True, timeout=5)
        if proc.returncode == 0:
            self.current_dir = proc.stdout.strip()
            return True
        return False

    def get_directory(self) -> str:
        return self.current_dir

    def _save_output(self, command: str, exit_code: int, stdout: str, stderr: str, exec_time: float):
        output_file = f"/tmp/command-output-{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        try:
            with open(output_file, 'w') as f:
                f.write(f"Timestamp: {datetime.now().isoformat()}\n")
                f.write(f"Command: {command}\n")
                f.write(f"Exit Code: {exit_code}\n")
                f.write(f"Execution Time: {exec_time:.2f}s\n")
                f.write("-" * 50 + "\n")
                f.write("STDOUT:\n")
                f.write(stdout if stdout else "(empty)\n")
                f.write("-" * 50 + "\n")
                f.write("STDERR:\n")
                f.write(stderr if stderr else "(empty)\n")
        except Exception:
            pass
