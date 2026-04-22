"""Security module for command validation and sanitization."""

import re
import shlex
from typing import Tuple, List, Optional


class CommandSecurity:
    """Handles command validation and security checks."""
    
    # Dangerous patterns to block
    FORBIDDEN_PATTERNS: List[str] = [
        r"rm\s+-rf\s+/",
        r"dd\s+if=",
        r"mkfs",
        r":\(\)\s*\{\s*:\|:&\s*\};:",
        r">\s*/dev/sd",
        r"chmod\s+-R\s+777\s+/",
        r"sudo\s+",
        r"su\s+-",
        r"passwd",
        r"visudo",
        r"crontab\s+-r",
        r"systemctl\s+(stop|disable|mask)",
        r"service\s+.*\s+stop",
        r"kill\s+-9\s+1",
        r"shutdown",
        r"reboot",
        r"halt",
        r"poweroff",
        r"init\s+[06]",
        r"telinit",
        r"mount.*\/dev",
        r"umount.*\/",
        r"fdisk",
        r"parted",
        r"wipefs",
        r"pvcreate|vgcreate|lvcreate",
    ]
    
    # Allowed path patterns
    ALLOWED_PATHS: List[str] = [
        r"^/tmp/",
        r"^/home/runner/",
        r"^/github/workspace/",
        r"^/github/home/",
        r"^/usr/local/",
        r"^/opt/",
        r"^\.",
        r"^[^/]",
    ]
    
    @classmethod
    def validate_command(cls, command: str, allowed_prefixes: Tuple[str, ...]) -> Tuple[bool, Optional[str]]:
        """
        Validate a command for security.
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not command or not command.strip():
            return False, "Empty command"
        
        command = command.strip()
        
        # Check command length
        if len(command) > 1000:
            return False, "Command too long"
        
        # Check for forbidden patterns
        for pattern in cls.FORBIDDEN_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return False, f"Forbidden pattern detected"
        
        # Parse command
        try:
            parts = shlex.split(command)
        except ValueError as e:
            return False, f"Invalid command syntax: {e}"
        
        if not parts:
            return False, "Empty command after parsing"
        
        # Check base command
        base_cmd = parts[0].split('/')[-1]
        if base_cmd not in allowed_prefixes:
            return False, f"Command '{base_cmd}' not allowed. Allowed: {', '.join(allowed_prefixes)}"
        
        # Check for command injection attempts
        dangerous_chars = [';', '&&', '||', '`', '$(']
        for char in dangerous_chars:
            if char in command:
                return False, f"Dangerous character '{char}' not allowed"
        
        # Validate file paths if present
        for part in parts[1:]:
            if part.startswith('/') or part.startswith('~/'):
                if not any(re.match(pattern, part) for pattern in cls.ALLOWED_PATHS):
                    return False, f"Path '{part}' not allowed"
        
        return True, None
    
    @classmethod
    def sanitize_command(cls, command: str) -> str:
        """Sanitize command for safe execution."""
        # Remove control characters
        command = re.sub(r'[\x00-\x1f\x7f]', '', command)
        # Normalize whitespace
        command = ' '.join(command.split())
        return command
