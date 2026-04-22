"""Command executor module with timeout and output capture."""

import subprocess
import time
import os
import sys
import tempfile
from typing import Tuple, Optional
from datetime import datetime
import threading


class CommandExecutor:
    """Executes shell commands with timeout and output capture."""
    
    def __init__(self, timeout: int = 300, max_output_size: int = 1_000_000):
        self.timeout = timeout
        self.max_output_size = max_output_size
        self.process: Optional[subprocess.Popen] = None
        self._killed = False
    
    def execute(self, command: str) -> Tuple[int, str, str, float]:
        """
        Execute a command and return exit code, stdout, stderr, and execution time.
        
        Args:
            command: The command to execute
            
        Returns:
            Tuple of (exit_code, stdout, stderr, execution_time)
        """
        start_time = time.time()
        stdout = ""
        stderr = ""
        exit_code = -1
        
        try:
            # Set safe environment
            env = os.environ.copy()
            env["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
            env["HOME"] = "/home/runner"
            
            # Create temporary files for output
            with tempfile.NamedTemporaryFile(mode='w+', suffix='.stdout', delete=False) as stdout_file, \
                 tempfile.NamedTemporaryFile(mode='w+', suffix='.stderr', delete=False) as stderr_file:
                
                stdout_path = stdout_file.name
                stderr_path = stderr_file.name
            
            # Start process
            self.process = subprocess.Popen(
                command,
                shell=True,
                executable='/bin/bash',
                stdout=open(stdout_path, 'w'),
                stderr=open(stderr_path, 'w'),
                env=env,
                cwd=os.getcwd(),
                preexec_fn=os.setsid if sys.platform != 'win32' else None
            )
            
            # Wait with timeout
            try:
                exit_code = self.process.wait(timeout=self.timeout)
            except subprocess.TimeoutExpired:
                self._kill_process()
                stderr = f"Command timed out after {self.timeout} seconds"
                exit_code = -1
            
            # Read output files
            if os.path.exists(stdout_path):
                with open(stdout_path, 'r', errors='ignore') as f:
                    stdout = f.read(self.max_output_size)
                    if len(stdout) == self.max_output_size:
                        stdout += "\n... [Output truncated]"
                os.unlink(stdout_path)
            
            if os.path.exists(stderr_path):
                with open(stderr_path, 'r', errors='ignore') as f:
                    stderr = f.read(self.max_output_size)
                    if len(stderr) == self.max_output_size:
                        stderr += "\n... [Output truncated]"
                os.unlink(stderr_path)
            
        except Exception as e:
            stderr = f"Execution error: {str(e)}"
            exit_code = -1
        
        execution_time = time.time() - start_time
        
        # Save output to file for logging
        self._save_output(command, exit_code, stdout, stderr, execution_time)
        
        return exit_code, stdout, stderr, execution_time
    
    def _kill_process(self):
        """Kill the running process and its children."""
        if self.process and not self._killed:
            self._killed = True
            try:
                if sys.platform != 'win32':
                    os.killpg(os.getpgid(self.process.pid), subprocess.signal.SIGTERM)
                    time.sleep(2)
                    if self.process.poll() is None:
                        os.killpg(os.getpgid(self.process.pid), subprocess.signal.SIGKILL)
                else:
                    self.process.terminate()
                    time.sleep(2)
                    if self.process.poll() is None:
                        self.process.kill()
            except (ProcessLookupError, OSError):
                pass
    
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
