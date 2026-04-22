"""Security module - DISABLED (NO RESTRICTIONS VERSION)."""

from typing import Tuple, Optional


class CommandSecurity:
    """No security restrictions - ALL COMMANDS ALLOWED."""
    
    @classmethod
    def validate_command(cls, command: str, allowed_prefixes: Tuple[str, ...] = ()) -> Tuple[bool, Optional[str]]:
        """
        Always returns valid - NO RESTRICTIONS.
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not command or not command.strip():
            return False, "Empty command"
        
        # NO VALIDATION - ALL COMMANDS ALLOWED
        return True, None
    
    @classmethod
    def sanitize_command(cls, command: str) -> str:
        """Minimal sanitization - keep newlines and special chars."""
        # Only remove null bytes and other control characters that break terminal
        import re
        command = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', command)
        return command
