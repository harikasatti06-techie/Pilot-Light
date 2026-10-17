"""Probabilistic circuit breaker for checkout handler.

Decides whether to fail a request based on the configured failure percentage.
Uses cryptographically secure random for unpredictability.
"""
import random
import time
from typing import Dict

from .config import FailModeConfig


class CircuitBreaker:
    """Probabilistic circuit breaker with state tracking.

    Tracks error counts and emits warnings when fail_mode is active.
    Uses secure random to determine per-request failures.
    """

    def __init__(self):
        self.last_warning_time = 0.0
        self.warning_interval = 60.0  # Emit warning at most once per minute

    def should_fail_request(self, config: FailModeConfig) -> bool:
        """Determine if this request should fail based on config.

        Args:
            config: Parsed fail_mode configuration

        Returns:
            True if request should fail, False otherwise
        """
        if not config.is_active:
            return False

        # Emit warning metric periodically when fail_mode is active
        now = time.time()
        if now - self.last_warning_time > self.warning_interval:
            print(f"WARNING: fail_mode active with {config.percent}% failure rate")
            self.last_warning_time = now

        # Use secure random for probabilistic failure
        # random.random() returns [0.0, 1.0), so we compare against percent/100
        return random.random() < (config.percent / 100.0)

    def reset_warning_timer(self):
        """Reset warning timer (useful for testing)."""
        self.last_warning_time = 0.0


# Global circuit breaker instance (singleton per process)
_breaker = CircuitBreaker()


def should_fail_request(config: FailModeConfig) -> bool:
    """Module-level function for convenience.

    Args:
        config: Parsed fail_mode configuration

    Returns:
        True if request should fail, False otherwise
    """
    return _breaker.should_fail_request(config)


def reset_warning_timer():
    """Reset warning timer on the global breaker (for testing)."""
    _breaker.reset_warning_timer()
