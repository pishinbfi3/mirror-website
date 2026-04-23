"""Custom exceptions for better error handling."""

class BotError(Exception):
    """Base exception for the bot."""

class ConfigError(BotError):
    """Configuration missing or invalid."""

class APIError(BotError):
    """Bale API returned an error."""

class CommandError(BotError):
    """Command execution failed."""

class StateError(BotError):
    """Snapshot / offset persistence error."""
