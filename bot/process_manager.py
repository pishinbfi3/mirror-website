import threading
import subprocess
import time
import os
import uuid
import signal
import json
from typing import Dict, Optional
from datetime import datetime

class ManagedProcess:
    def __init__(self, job_id: str, command: str, timeout: int = 300):
        self.job_id = job_id
        self.command = command
        self.timeout = timeout
        self.process: Optional[subprocess.Popen] = None
        self.stdout_lines = []
        self.stderr_lines = []
        self.exit_code = None
        self.start_time = time.time()
        self.status = "pending"
        self.thread = None
        
    def start(self):
        self.status = "running"
        self.thread = threading.Thread(target=self._run)
        self.thread.daemon = True
        self.thread.start()
        
    def _run(self):
        try:
            self.process = subprocess.Popen(
                self.command,
                shell=True,
                executable='/bin/bash',
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                preexec_fn=os.setsid
            )
            stdout, stderr = self.process.communicate(timeout=self.timeout)
            self.exit_code = self.process.returncode
            self.stdout_lines = stdout.splitlines()
            self.stderr_lines = stderr.splitlines()
            self.status = "completed"
        except subprocess.TimeoutExpired:
            self._kill()
            self.status = "timeout"
        except Exception as e:
            self.stderr_lines = [str(e)]
            self.status = "failed"
            
    def _kill(self):
        if self.process:
            os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
            time.sleep(0.5)
            if self.process.poll() is None:
                os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
            self.status = "killed"
            
    def kill(self):
        if self.status == "running":
            self._kill()
            
    def get_output(self, max_lines=100) -> str:
        lines = self.stdout_lines[-max_lines:] + self.stderr_lines[-max_lines:]
        return "\n".join(lines) if lines else "(no output yet)"
    
    def get_info(self) -> str:
        runtime = time.time() - self.start_time
        return f"`{self.job_id}` | {self.status} | {runtime:.1f}s | {self.command[:60]}"

    def to_dict(self):
        return {
            'job_id': self.job_id,
            'command': self.command,
            'timeout': self.timeout,
            'stdout_lines': self.stdout_lines[-1000:],
            'stderr_lines': self.stderr_lines[-1000:],
            'exit_code': self.exit_code,
            'start_time': self.start_time,
            'status': self.status
        }

    @classmethod
    def from_dict(cls, data):
        proc = cls(data['job_id'], data['command'], data['timeout'])
        proc.stdout_lines = data.get('stdout_lines', [])
        proc.stderr_lines = data.get('stderr_lines', [])
        proc.exit_code = data.get('exit_code')
        proc.start_time = data.get('start_time', time.time())
        proc.status = data.get('status', 'completed')
        # فرآیندهای در حال اجرا در زمان snapshot قابل بازیابی نیستند
        if proc.status in ('running', 'pending'):
            proc.status = 'interrupted'
        proc.process = None
        proc.thread = None
        return proc


class ProcessManager:
    def __init__(self):
        self.jobs: Dict[str, ManagedProcess] = {}
        self.lock = threading.Lock()
        
    def submit(self, command: str, timeout: int = 300) -> str:
        job_id = str(uuid.uuid4())[:8]
        proc = ManagedProcess(job_id, command, timeout)
        with self.lock:
            self.jobs[job_id] = proc
        proc.start()
        return job_id
    
    def kill(self, job_id: str) -> bool:
        with self.lock:
            proc = self.jobs.get(job_id)
        if proc and proc.status == "running":
            proc.kill()
            return True
        return False
    
    def list_jobs(self) -> str:
        with self.lock:
            if not self.jobs:
                return "📭 No active or recent jobs."
            lines = ["**📋 Job List:**"]
            for job in self.jobs.values():
                lines.append(job.get_info())
            return "\n".join(lines)
    
    def get_output(self, job_id: str) -> Optional[str]:
        with self.lock:
            proc = self.jobs.get(job_id)
        if proc:
            return proc.get_output()
        return None
    
    def cleanup_old(self, max_age_seconds=3600):
        now = time.time()
        with self.lock:
            to_remove = [jid for jid, p in self.jobs.items() 
                         if p.status in ("completed", "killed", "timeout", "failed", "interrupted") 
                         and now - p.start_time > max_age_seconds]
            for jid in to_remove:
                del self.jobs[jid]

    def save_snapshot(self, filepath: str):
        data = {}
        with self.lock:
            for jid, proc in self.jobs.items():
                data[jid] = proc.to_dict()
        with open(filepath, 'w') as f:
            json.dump(data, f)
    
    def load_snapshot(self, filepath: str):
        if not os.path.exists(filepath):
            return
        with open(filepath, 'r') as f:
            data = json.load(f)
        with self.lock:
            self.jobs.clear()
            for jid, proc_data in data.items():
                proc = ManagedProcess.from_dict(proc_data)
                self.jobs[jid] = proc
