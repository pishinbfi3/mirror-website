"""Configuration management using Pydantic Settings."""

from typing import Optional
from pydantic import Field, HttpUrl, PositiveInt
from pydantic_settings import BaseSettings


class BotConfig(BaseSettings):
    """All bot configuration, loaded from environment variables."""

    # Required secrets
    bot_token: str = Field(..., env="BALE_BOT_TOKEN")
    chat_id: str = Field(..., env="BALE_CHAT_ID")

    # API settings
    api_base_url: HttpUrl = Field(
        "https://tapi.bale.ai", env="BALE_API_BASE_URL"
    )
    api_timeout: PositiveInt = Field(30, env="BALE_API_TIMEOUT")

    # Polling behaviour
    poll_timeout: PositiveInt = Field(30, env="BALE_POLL_TIMEOUT")
    poll_interval: float = Field(1.0, env="BALE_POLL_INTERVAL")
    max_retries: PositiveInt = Field(3, env="BALE_MAX_RETRIES")

    # Command execution
    command_timeout: PositiveInt = Field(300, env="BALE_COMMAND_TIMEOUT")
    max_output_chars: PositiveInt = Field(4_000_000, env="BALE_MAX_OUTPUT")

    # File handling
    max_message_length: PositiveInt = Field(4000, env="BALE_MAX_MSG_LEN")
    chunk_size: PositiveInt = 9 * 1024 * 1024  # 9 MiB for split files

    # State persistence
    state_dir: str = Field("/tmp/bale_bot", env="BALE_STATE_DIR")
    offset_file: str = "offset.txt"
    snapshot_file: str = "snapshot.json"

    class Config:
        env_file = ".env"
        case_sensitive = False
