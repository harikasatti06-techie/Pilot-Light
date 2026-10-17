"""Configuration parser and validator for fail_mode parameter.

Supports two formats:
- Simple: "off" or "on:N" where N is 0-100 (percent)
- Legacy: "on" or "off" (treated as on:100 and on:0 respectively)

Invalid values default to off with error logging.
"""
import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class FailModeConfig:
    """Parsed fail_mode configuration."""
    mode: str  # "on" or "off"
    percent: int  # 0-100

    @property
    def is_active(self) -> bool:
        return self.mode == "on" and self.percent > 0


def parse_fail_mode(value: str) -> FailModeConfig:
    """Parse and validate fail_mode parameter value.

    Args:
        value: Raw parameter value (e.g., "off", "on", "on:50")

    Returns:
        FailModeConfig with validated mode and percent

    Examples:
        >>> parse_fail_mode("off")
        FailModeConfig(mode='off', percent=0)
        >>> parse_fail_mode("on:50")
        FailModeConfig(mode='on', percent=50)
        >>> parse_fail_mode("on")  # legacy format
        FailModeConfig(mode='on', percent=100)
    """
    value = value.strip().lower()

    # Handle "off"
    if value == "off":
        return FailModeConfig(mode="off", percent=0)

    # Handle "on" (legacy format - 100%)
    if value == "on":
        return FailModeConfig(mode="on", percent=100)

    # Handle "on:N" format
    match = re.match(r"^on:(\d+)$", value)
    if match:
        percent = int(match.group(1))
        if 0 <= percent <= 100:
            return FailModeConfig(mode="on", percent=percent)
        # Invalid percent - log and fallback to off
        print(f"ERROR: Invalid fail_mode percent {percent} (must be 0-100), defaulting to off")
        return FailModeConfig(mode="off", percent=0)

    # Invalid format - log and fallback to off
    print(f"ERROR: Invalid fail_mode value '{value}', defaulting to off")
    return FailModeConfig(mode="off", percent=0)
