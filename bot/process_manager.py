"""Async background job manager."""

import asyncio
import uuid
from typing import Dict, Optional, List
from dataclasses import dataclass, field
from datetime import datetime

from .logger import get_logger

logger = get_logger(__name__)


@dataclass
class BackgroundJob:
    job_id: str
    command: str
    status: str = "pending"  # pending, running, completed, failed, killed
    exit_code: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    created_at: float = field(default_factory=datetime.now().timestamp)
    finished_at: Optional[float] = None

    def to_dict(self):
        return {
            "job_id": self.job_id,
            "command": self.command,
            "status": self.status,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }

    @classmethod
    def from_dict(cls, data):
        return cls(**data)


class ProcessManager:
    """Manages asynchronous background commands."""

    def __init__(self, max_concurrent: int = 5):
        self.jobs: Dict[str, BackgroundJob] = {}
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._tasks: Dict[str, asyncio.Task] = {}

    async def submit(self, command: str, timeout: int = 300) -> str:
        """Start a command in background, return job_id."""
        job_id = str(uuid.uuid4())[:8]
        job = BackgroundJob(job_id=job_id, command=command, status="pending")
        self.jobs[job_id] = job

        async def _run():
            async with self._semaphore:
                job.status = "running"
                try:
                    proc = await asyncio.create_subprocess_shell(
                        command,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        executable="/bin/bash",
                    )
                    stdout, stderr = await asyncio.wait_for(
                        proc.communicate(), timeout=timeout
                    )
                    job.exit_code = proc.returncode
                    job.stdout = stdout.decode("utf-8", errors="replace")[:10000]
                    job.stderr = stderr.decode("utf-8", errors="replace")[:10000]
                    job.status = "completed"
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
                    job.status = "timeout"
                    job.stderr = f"Timeout after {timeout}s"
                except Exception as e:
                    job.status = "failed"
                    job.stderr = str(e)
                finally:
                    job.finished_at = datetime.now().timestamp()
                    logger.info(f"Background job {job_id} finished: {job.status}")

        task = asyncio.create_task(_run())
        self._tasks[job_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(job_id, None))
        return job_id

    async def kill(self, job_id: str) -> bool:
        """Terminate a running background job."""
        task = self._tasks.get(job_id)
        if task and not task.done():
            task.cancel()
            self.jobs[job_id].status = "killed"
            self.jobs[job_id].finished_at = datetime.now().timestamp()
            return True
        return False

    def list_jobs(self, limit: int = 20) -> List[BackgroundJob]:
        """Return recent jobs sorted by creation time descending."""
        jobs = list(self.jobs.values())
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]

    async def get_output(self, job_id: str) -> Optional[str]:
        """Return combined stdout/stderr for a job."""
        job = self.jobs.get(job_id)
        if not job:
            return None
        if job.status in ("pending", "running"):
            return "Job still running, no final output yet."
        out = f"Command: {job.command}\nStatus: {job.status}\n"
        if job.exit_code is not None:
            out += f"Exit code: {job.exit_code}\n"
        if job.stdout:
            out += f"\n--- STDOUT ---\n{job.stdout}\n"
        if job.stderr:
            out += f"\n--- STDERR ---\n{job.stderr}\n"
        return out

    async def cleanup_old(self, max_age_seconds: int = 3600) -> None:
        """Remove jobs older than max_age_seconds."""
        now = datetime.now().timestamp()
        to_remove = [
            jid
            for jid, job in self.jobs.items()
            if job.finished_at and (now - job.finished_at) > max_age_seconds
        ]
        for jid in to_remove:
            del self.jobs[jid]
