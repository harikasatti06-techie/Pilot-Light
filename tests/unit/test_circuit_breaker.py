"""Unit tests for services/checkout/circuit_breaker.py"""
import sys
import time
from pathlib import Path
from unittest.mock import patch

# Add services to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "services"))

from checkout.circuit_breaker import CircuitBreaker, should_fail_request, reset_warning_timer
from checkout.config import FailModeConfig


class TestCircuitBreaker:
    """Tests for CircuitBreaker class."""

    def test_inactive_config_never_fails(self):
        """Test that inactive config (off) never fails requests."""
        breaker = CircuitBreaker()
        config = FailModeConfig(mode="off", percent=0)

        # Try 100 times, should never fail
        for _ in range(100):
            assert not breaker.should_fail_request(config)

    def test_zero_percent_never_fails(self):
        """Test that on:0 never fails requests."""
        breaker = CircuitBreaker()
        config = FailModeConfig(mode="on", percent=0)

        # Try 100 times, should never fail
        for _ in range(100):
            assert not breaker.should_fail_request(config)

    def test_hundred_percent_always_fails(self):
        """Test that on:100 always fails requests."""
        breaker = CircuitBreaker()
        config = FailModeConfig(mode="on", percent=100)

        # Try 100 times, should always fail
        for _ in range(100):
            assert breaker.should_fail_request(config)

    def test_probabilistic_failure_approximate_rate(self):
        """Test that failure rate is approximately correct for on:50."""
        breaker = CircuitBreaker()
        config = FailModeConfig(mode="on", percent=50)

        # Run 1000 times to get statistical significance
        failures = sum(1 for _ in range(1000) if breaker.should_fail_request(config))

        # Allow 5% margin of error (50% ± 5% = 450-550 failures out of 1000)
        assert 450 <= failures <= 550, f"Expected ~500 failures, got {failures}"

    def test_probabilistic_failure_ten_percent(self):
        """Test that failure rate is approximately correct for on:10."""
        breaker = CircuitBreaker()
        config = FailModeConfig(mode="on", percent=10)

        # Run 1000 times
        failures = sum(1 for _ in range(1000) if breaker.should_fail_request(config))

        # Allow 5% margin of error (10% ± 5% = 50-150 failures out of 1000)
        assert 50 <= failures <= 150, f"Expected ~100 failures, got {failures}"

    def test_warning_emitted_once_per_minute(self, capsys):
        """Test that warning is emitted at most once per minute."""
        breaker = CircuitBreaker()
        breaker.warning_interval = 0.1  # Set to 100ms for testing
        config = FailModeConfig(mode="on", percent=50)

        # First call should emit warning
        breaker.should_fail_request(config)
        captured = capsys.readouterr()
        assert "WARNING: fail_mode active with 50% failure rate" in captured.out

        # Immediate second call should NOT emit warning
        breaker.should_fail_request(config)
        captured = capsys.readouterr()
        assert "WARNING" not in captured.out

        # After waiting, should emit again
        time.sleep(0.15)
        breaker.should_fail_request(config)
        captured = capsys.readouterr()
        assert "WARNING: fail_mode active with 50% failure rate" in captured.out

    def test_reset_warning_timer(self, capsys):
        """Test that reset_warning_timer allows immediate warning."""
        breaker = CircuitBreaker()
        config = FailModeConfig(mode="on", percent=10)

        # Emit warning
        breaker.should_fail_request(config)
        capsys.readouterr()  # Clear

        # Reset timer
        breaker.reset_warning_timer()

        # Should emit warning immediately
        breaker.should_fail_request(config)
        captured = capsys.readouterr()
        assert "WARNING: fail_mode active with 10% failure rate" in captured.out


class TestModuleLevelFunctions:
    """Tests for module-level convenience functions."""

    def test_should_fail_request_module_function(self):
        """Test that module-level should_fail_request works."""
        reset_warning_timer()  # Reset global state
        config = FailModeConfig(mode="off", percent=0)
        assert not should_fail_request(config)

        config = FailModeConfig(mode="on", percent=100)
        assert should_fail_request(config)

    def test_reset_warning_timer_module_function(self, capsys):
        """Test that module-level reset_warning_timer works."""
        config = FailModeConfig(mode="on", percent=25)

        # Emit warning
        should_fail_request(config)
        capsys.readouterr()

        # Reset
        reset_warning_timer()

        # Should emit immediately
        should_fail_request(config)
        captured = capsys.readouterr()
        assert "WARNING" in captured.out
