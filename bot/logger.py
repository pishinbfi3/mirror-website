"""Logging configuration with rotation."""

import logging
import sys
from logging.handlers import RotatingFileHandler


def setup_logging(log_level: str = "INFO") -> None:
    """Configure structured logging to console and rotating file."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, log_level.upper()))

    # Remove any existing handlers
    for h in root.handlers[:]:
        root.removeHandler(h)

    # Console handler (colours optional)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    root.addHandler(console)

    # File handler with rotation (max 10 MiB, keep 5)
    file_handler = RotatingFileHandler(
        "/tmp/bale_bot.log", maxBytes=10_485_760, backupCount=5
    )
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    root.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """Convenience function to get a logger instance."""
    return logging.getLogger(name)
