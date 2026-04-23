"""Main polling loop with backoff and graceful shutdown."""

import asyncio
import signal
from typing import Optional

from .config import BotConfig
from .api_client import BaleAPIClient
from .executor import CommandExecutor
from .process_manager import ProcessManager
from .command_handler import CommandHandler
from .state_manager import StateManager
from .logger import get_logger

logger = get_logger(__name__)


class BaleBot:
    """Orchestrates the polling loop and components."""

    def __init__(self, config: BotConfig):
        self.config = config
        self.api: Optional[BaleAPIClient] = None
        self.executor: Optional[CommandExecutor] = None
        self.pm: Optional[ProcessManager] = None
        self.state: Optional[StateManager] = None
        self.handler: Optional[CommandHandler] = None
        self._running = True
        self._current_offset = 0

    async def start(self):
        """Initialize all components and start polling."""
        logger.info("Starting Bale SSH Bot...")

        self.api = BaleAPIClient(self.config)
        await self.api.__aenter__()  # manually enter context

        self.executor = CommandExecutor(self.config)
        self.pm = ProcessManager()
        self.state = StateManager(self.config)

        # Restore snapshot
        cur_dir, jobs = await self.state.load_snapshot()
        if cur_dir and os.path.isdir(cur_dir):
            self.executor.set_directory(cur_dir)
            logger.info(f"Restored working directory: {cur_dir}")
        if jobs:
            self.pm.jobs = jobs
            logger.info(f"Restored {len(jobs)} background jobs (completed only)")

        self.handler = CommandHandler(self.config, self.executor, self.pm, self.api)

        self._current_offset = self.state.get_offset()
        logger.info(f"Starting polling from offset {self._current_offset}")

        # Setup signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))

        await self._poll_loop()

    async def stop(self):
        """Graceful shutdown: save snapshot, close connections."""
        logger.info("Stopping bot...")
        self._running = False
        # Save snapshot
        await self.state.save_snapshot(self.executor.get_directory(), self.pm.jobs)
        # Clean old background jobs
        await self.pm.cleanup_old()
        if self.api:
            await self.api.__aexit__()
        logger.info("Bot stopped.")

    async def _poll_loop(self):
        """Main polling loop with exponential backoff."""
        retries = 0
        while self._running:
            try:
                updates = await self.api.get_updates(
                    offset=self._current_offset + 1 if self._current_offset else None,
                    timeout=self.config.poll_timeout,
                )
                retries = 0  # reset on success
                for update in updates:
                    if not self._running:
                        break
                    if update.message:
                        await self._process_update(update)
                    self._current_offset = update.update_id
                    self.state.save_offset(self._current_offset)
            except Exception as e:
                logger.exception(f"Polling error: {e}")
                retries += 1
                wait = min(30, 2 ** retries)
                await asyncio.sleep(wait)

    async def _process_update(self, update):
        """Handle a single update (message or edited message)."""
        msg = update.message or update.edited_message
        if not msg:
            return
        # Ignore old messages (> 30 sec)
        import time
        now = time.time()
        if now - msg.date.timestamp() > 30:
            logger.debug("Skipping old message")
            return
        if str(msg.chat.id) != self.config.chat_id:
            logger.warning(f"Ignoring chat {msg.chat.id}")
            return

        logger.info(f"Processing from {msg.from_.id}: {msg.text or '[document]'}")
        response_text, file_path = await self.handler.handle_message(msg)
        if response_text:
            await self.api.send_message(
                self.config.chat_id, response_text, msg.message_id
            )
        if file_path and os.path.exists(file_path):
            await self.api.send_document(
                self.config.chat_id, file_path, caption="Command output"
            )
            os.unlink(file_path)

        # Handle /stop command
        if msg.text and msg.text.strip().lower() == "/stop":
            await self.stop()
