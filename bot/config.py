"""Configuration module for Bale SSH Bot - reads from environment."""

import os
from pydantic import Field, HttpUrl, PositiveInt
from pydantic.dataclasses import dataclass


@dataclass
class BotConfig:
    """Bot configuration settings - loaded from environment variables."""

    bot_token: str
    chat_id: str
    api_base_url: HttpUrl = Field(default="https://tapi.bale.ai")
    api_timeout: PositiveInt = 30
    poll_timeout: PositiveInt = 30
    poll_interval: float = 1.0
    max_retries: PositiveInt = 3
    command_timeout: PositiveInt = 300
    max_output_chars: PositiveInt = 4_000_000
    max_message_length: PositiveInt = 4000
    chunk_size: PositiveInt = 9 * 1024 * 1024   # 9 MiB
    state_dir: str = "/tmp/bale_bot"
    offset_file: str = "offset.txt"
    snapshot_file: str = "snapshot.json"

    @classmethod
    def from_env(cls) -> "BotConfig":
        """Create config from environment variables (same as original)."""
        bot_token = os.environ.get("BALE_BOT_TOKEN")
        chat_id = os.environ.get("BALE_CHAT_ID")

        if not bot_token or not chat_id:
            raise ValueError("BALE_BOT_TOKEN and BALE_CHAT_ID must be set")

        kwargs = {
            "bot_token": bot_token,
            "chat_id": chat_id,
        }

        # Optional overrides
        if os.environ.get("BALE_API_BASE_URL"):
            kwargs["api_base_url"] = os.environ["BALE_API_BASE_URL"]
        if os.environ.get("BALE_API_TIMEOUT"):
            kwargs["api_timeout"] = int(os.environ["BALE_API_TIMEOUT"])
        if os.environ.get("BALE_POLL_TIMEOUT"):
            kwargs["poll_timeout"] = int(os.environ["BALE_POLL_TIMEOUT"])
        if os.environ.get("BALE_COMMAND_TIMEOUT"):
            kwargs["command_timeout"] = int(os.environ["BALE_COMMAND_TIMEOUT"])
        if os.environ.get("BALE_MAX_OUTPUT"):
            kwargs["max_output_chars"] = int(os.environ["BALE_MAX_OUTPUT"])
        if os.environ.get("BALE_STATE_DIR"):
            kwargs["state_dir"] = os.environ["BALE_STATE_DIR"]

        return cls(**kwargs)
