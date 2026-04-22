"""Command executor with manual state tracking – cd handled internally."""

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
        self.env["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

    def execute(self, command: str) -> Tuple[int, str, str, float]:
        """
        Execute a command.
        For `cd` commands, we change the internal directory without running a subprocess.
        For other commands, we prefix with `cd '{current_dir}' &&` to preserve state.
        """
        start_time = time.time()
        cmd_stripped = command.strip()

        # Handle cd command internally
        if cmd_stripped.startswith('cd '):
            return self._handle_cd(cmd_stripped, start_time)

        # For any other command, run in a subprocess with current directory prefix
        final_command = command
        if self.current_dir:
            # Escape single quotes in directory name
            safe_dir = self.current_dir.replace("'", "'\\''")
            final_command = f"cd '{safe_dir}' && {command}"

        try:
            with tempfile.NamedTemporaryFile(mode='w+', suffix='.out', delete=False) as out_f, \
                 tempfile.NamedTemporaryFile(mode='w+', suffix='.err', delete=False) as err_f:

                proc = subprocess.Popen(
                    final_command,
                    shell=True,
                    executable='/bin/bash',
                    stdout=out_f,
                    stderr=err_f,
                    env=self.env,
                    cwd="/",  # we use explicit cd, so cwd doesn't matter
                    text=True
                )

                try:
                    exit_code = proc.wait(timeout=self.timeout)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                    stderr = f"Command timed out after {self.timeout} seconds"
                    exit_code = -1

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

        execution_time = time.time() - start_time
        self._save_output(command, exit_code, stdout, stderr, execution_time)
        return exit_code, stdout, stderr, execution_time

    def _handle_cd(self, command: str, start_time: float) -> Tuple[int, str, str, float]:
        """Handle cd command without subprocess."""
        # Extract target directory (remove 'cd ' and strip quotes)
        target = command[3:].strip()
        target = target.strip("'\"")
        if not target:
            return 1, "", "cd: missing directory", 0.0

        # Resolve relative to current_dir
        if target.startswith('/'):
            new_dir = target
        else:
            new_dir = os.path.join(self.current_dir, target)
        new_dir = os.path.abspath(new_dir)

        if os.path.isdir(new_dir):
            self.current_dir = new_dir
            execution_time = time.time() - start_time
            return 0, f"Changed directory to {self.current_dir}", "", execution_time
        else:
            execution_time = time.time() - start_time
            return 1, "", f"cd: {target}: No such file or directory", execution_time

    def set_directory(self, path: str) -> bool:
        """Change the current working directory (manual state update)."""
        if os.path.isdir(path):
            self.current_dir = os.path.abspath(path)
            return True
        # Try relative to current_dir
        test_path = os.path.join(self.current_dir, path)
        if os.path.isdir(test_path):
            self.current_dir = test_path
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
