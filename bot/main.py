#!/usr/bin/env python3
"""Entry point – sets up logging, runs the bot, handles signals."""

import asyncio
import sys

from .config import BotConfig
from .bot import BaleBot
from .logger import setup_logging
from .exceptions import ConfigError


async def main():
    """Async main entry."""
    setup_logging("INFO")
    try:
        config = BotConfig.from_env()   # ← changed from BotConfig()
    except Exception as e:
        print(f"❌ Configuration error: {e}", file=sys.stderr)
        sys.exit(1)

    bot = BaleBot(config)
    try:
        await bot.start()
    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user")
    except Exception as e:
        print(f"❌ Fatal error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
