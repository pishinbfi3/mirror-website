"""Command executor with persistent shell session and timeout capture."""

import subprocess
import time
import os
import sys
import tempfile
import threading
import select
from typing import Tuple, Optional
from datetime import datetime


class PersistentShell:
    """Maintains a persistent bash session with state (cwd, env, variables)."""

    def __init__(self, timeout: int = 300, max_output_size: int = 1_000_000):
        self.timeout = timeout
        self.max_output_size = max_output_size
        self.process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._start_shell()

    def _start_shell(self):
        """Start a new bash process with pipes."""
        env = os.environ.copy()
        env["PS1"] = "PROMPT_READY> "
        env["TERM"] = "dumb"
        self.process = subprocess.Popen(
            ["/bin/bash", "--noediting", "-i"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            bufsize=1,
            universal_newlines=True,
        )
        # Wait for initial prompt
        self._read_until_prompt()

    def _read_until_prompt(self, timeout: float = 5.0) -> str:
        """Read output until the custom prompt appears."""
        output = []
        start = time.time()
        while (time.time() - start) < timeout:
            rlist, _, _ = select.select([self.process.stdout], [], [], 0.2)
            if rlist:
                char = self.process.stdout.read(1)
                if char:
                    output.append(char)
                    if "PROMPT_READY>" in "".join(output[-20:]):
                        break
        return "".join(output).replace("PROMPT_READY>", "").strip()

    def execute(self, command: str) -> Tuple[int, str, str, float]:
        """Send a command to the persistent shell, return (exit, stdout, stderr, exec_time)."""
        start_time = time.time()
        with self._lock:
            # Send command
            self.process.stdin.write(command + "\n")
            self.process.stdin.flush()
            # Read until next prompt or timeout
            output_lines = []
            stderr_lines = []
            start_read = time.time()
            while (time.time() - start_read) < self.timeout:
                rlist, _, _ = select.select([self.process.stdout, self.process.stderr], [], [], 0.2)
                if not rlist:
                    # No output for a while, assume command finished
                    # Check if prompt is already in output
                    if "PROMPT_READY>" in "".join(output_lines[-50:]):
                        break
                    continue
                for fd in rlist:
                    if fd == self.process.stdout:
                        char = self.process.stdout.read(1)
                        if char:
                            output_lines.append(char)
                    elif fd == self.process.stderr:
                        char = self.process.stderr.read(1)
                        if char:
                            stderr_lines.append(char)
                # Break if we see the prompt
                if "PROMPT_READY>" in "".join(output_lines[-50:]):
                    break
            # Remove the prompt line from output
            full_output = "".join(output_lines)
            if "PROMPT_READY>" in full_output:
                full_output = full_output.rsplit("PROMPT_READY>", 1)[0].rstrip()
            full_stderr = "".join(stderr_lines)
            # Get exit code of last command (bash sends $? after command)
            # We'll send a special echo command to capture exit code
            self.process.stdin.write("echo $?\n")
            self.process.stdin.flush()
            exit_code_str = self._read_until_prompt(timeout=2).strip()
            try:
                exit_code = int(exit_code_str.split()[-1])
            except:
                exit_code = -1

            execution_time = time.time() - start_time
            # Truncate output if needed
            if len(full_output) > self.max_output_size:
                full_output = full_output[:self.max_output_size] + "\n... [Output truncated]"
            if len(full_stderr) > self.max_output_size:
                full_stderr = full_stderr[:self.max_output_size] + "\n... [Output truncated]"

            self._save_output(command, exit_code, full_output, full_stderr, execution_time)
            return exit_code, full_output, full_stderr, execution_time

    def close(self):
        """Terminate the shell process."""
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None

    def _save_output(self, command: str, exit_code: int, stdout: str, stderr: str, exec_time: float):
        """Save command output to a log file."""
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
