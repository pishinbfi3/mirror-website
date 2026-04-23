"""Persistent state (offset, snapshot, working directory)."""

import json
import os
import asyncio
from typing import Optional

from .config import BotConfig
from .exceptions import StateError
from .logger import get_logger

logger = get_logger(__name__)


class StateManager:
    """Manages update offset and full snapshot."""

    def __init__(self, config: BotConfig):
        self.config = config
        self._ensure_state_dir()

    def _ensure_state_dir(self) -> None:
        os.makedirs(self.config.state_dir, exist_ok=True)

    def _offset_path(self) -> str:
        return os.path.join(self.config.state_dir, self.config.offset_file)

    def _snapshot_path(self) -> str:
        return os.path.join(self.config.state_dir, self.config.snapshot_file)

    def get_offset(self) -> int:
        """Read last processed update_id."""
        try:
            with open(self._offset_path(), "r") as f:
                return int(f.read().strip())
        except (FileNotFoundError, ValueError):
            return 0

    def save_offset(self, offset: int) -> None:
        """Store current offset."""
        try:
            with open(self._offset_path(), "w") as f:
                f.write(str(offset))
        except Exception as e:
            logger.error(f"Failed to save offset: {e}")
            raise StateError(f"Cannot save offset: {e}")

    async def save_snapshot(self, current_dir: str, jobs: dict) -> str:
        """Save full state (directory + background jobs)."""
        data = {
            "current_dir": current_dir,
            "timestamp": asyncio.get_event_loop().time(),
            "jobs": {jid: job.to_dict() for jid, job in jobs.items()},
        }
        path = self._snapshot_path()
        try:
            # atomic write via tempfile
            tmp = path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, path)
            logger.info(f"Snapshot saved to {path}")
            return path
        except Exception as e:
            logger.error(f"Snapshot save failed: {e}")
            raise StateError(f"Cannot save snapshot: {e}")

    async def load_snapshot(self) -> tuple[Optional[str], Optional[dict]]:
        """Load snapshot, return (current_dir, jobs_dict) or (None, None)."""
        path = self._snapshot_path()
        if not os.path.exists(path):
            return None, None
        try:
            with open(path, "r") as f:
                data = json.load(f)
            current_dir = data.get("current_dir")
            jobs_data = data.get("jobs", {})
            # Convert back to BackgroundJob objects (requires import)
            from .process_manager import BackgroundJob
            jobs = {}
            for jid, job_dict in jobs_data.items():
                jobs[jid] = BackgroundJob.from_dict(job_dict)
            logger.info(f"Snapshot loaded from {path}")
            return current_dir, jobs
        except Exception as e:
            logger.error(f"Snapshot load failed: {e}")
            return None, None
