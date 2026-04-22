"""Configuration module for Bale SSH Bot."""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class BotConfig:
    """Bot configuration settings."""
    
    bot_token: str
    chat_id: str
    api_base_url: str = "https://tapi.bale.ai"
    update_offset_file: str = "/tmp/bale-bot-offset.txt"
    log_file: str = "/tmp/bale-bot-execution.log"
    max_message_length: int = 4000
    timeout_seconds: int = 300
    allowed_commands: tuple = (
        "ls", "pwd", "whoami", "date", "uname", "df", "free",
        "ps", "netstat", "ifconfig", "ip", "ping", "curl",
        "wget", "git", "python", "python3", "pip", "npm",
        "node", "go", "rustc", "cargo", "gcc", "g++", "make",
        "docker", "kubectl", "helm", "terraform", "ansible",
        "cat", "head", "tail", "grep", "awk", "sed", "find",
        "echo", "env", "printenv", "hostname", "uptime"
    )
    
    @classmethod
    def from_env(cls) -> "BotConfig":
        """Create config from environment variables."""
        bot_token = os.environ.get("BALE_BOT_TOKEN")
        chat_id = os.environ.get("BALE_CHAT_ID")
        
        if not bot_token or not chat_id:
            raise ValueError("BALE_BOT_TOKEN and BALE_CHAT_ID must be set")
        
        return cls(
            bot_token=bot_token,
            chat_id=chat_id
        )
