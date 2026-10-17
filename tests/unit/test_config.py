"""Unit tests for services/checkout/config.py"""
import pytest
import sys
from pathlib import Path

# Add services to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "services"))

from checkout.config import parse_fail_mode, FailModeConfig


class TestParseFailMode:
    """Tests for parse_fail_mode function."""

    def test_parse_off(self):
        """Test parsing 'off' value."""
        config = parse_fail_mode("off")
        assert config.mode == "off"
        assert config.percent == 0
        assert not config.is_active

    def test_parse_off_with_whitespace(self):
        """Test parsing 'off' with leading/trailing whitespace."""
        config = parse_fail_mode("  off  ")
        assert config.mode == "off"
        assert config.percent == 0

    def test_parse_legacy_on(self):
        """Test parsing legacy 'on' format (should be 100%)."""
        config = parse_fail_mode("on")
        assert config.mode == "on"
        assert config.percent == 100
        assert config.is_active

    def test_parse_on_with_zero_percent(self):
        """Test parsing 'on:0' (active but 0% failure)."""
        config = parse_fail_mode("on:0")
        assert config.mode == "on"
        assert config.percent == 0
        assert not config.is_active  # 0% means not active

    def test_parse_on_with_low_percent(self):
        """Test parsing 'on:10' (10% failure rate)."""
        config = parse_fail_mode("on:10")
        assert config.mode == "on"
        assert config.percent == 10
        assert config.is_active

    def test_parse_on_with_fifty_percent(self):
        """Test parsing 'on:50' (50% failure rate)."""
        config = parse_fail_mode("on:50")
        assert config.mode == "on"
        assert config.percent == 50
        assert config.is_active

    def test_parse_on_with_hundred_percent(self):
        """Test parsing 'on:100' (100% failure rate)."""
        config = parse_fail_mode("on:100")
        assert config.mode == "on"
        assert config.percent == 100
        assert config.is_active

    def test_parse_invalid_percent_over_100(self, capsys):
        """Test parsing 'on:150' (invalid, should default to off)."""
        config = parse_fail_mode("on:150")
        assert config.mode == "off"
        assert config.percent == 0
        # Check error was printed
        captured = capsys.readouterr()
        assert "Invalid fail_mode percent 150" in captured.out

    def test_parse_invalid_percent_negative(self, capsys):
        """Test parsing 'on:-10' (invalid format, should default to off)."""
        config = parse_fail_mode("on:-10")
        assert config.mode == "off"
        assert config.percent == 0
        # Check error was printed
        captured = capsys.readouterr()
        assert "Invalid fail_mode value" in captured.out

    def test_parse_invalid_format(self, capsys):
        """Test parsing invalid format like 'maybe'."""
        config = parse_fail_mode("maybe")
        assert config.mode == "off"
        assert config.percent == 0
        # Check error was printed
        captured = capsys.readouterr()
        assert "Invalid fail_mode value 'maybe'" in captured.out

    def test_parse_invalid_format_with_text(self, capsys):
        """Test parsing 'on:abc' (invalid format)."""
        config = parse_fail_mode("on:abc")
        assert config.mode == "off"
        assert config.percent == 0

    def test_parse_empty_string(self, capsys):
        """Test parsing empty string."""
        config = parse_fail_mode("")
        assert config.mode == "off"
        assert config.percent == 0

    def test_case_insensitivity(self):
        """Test that parsing is case-insensitive."""
        configs = [
            parse_fail_mode("OFF"),
            parse_fail_mode("Off"),
            parse_fail_mode("ON:50"),
            parse_fail_mode("On:50"),
        ]
        assert configs[0].mode == "off"
        assert configs[1].mode == "off"
        assert configs[2].mode == "on" and configs[2].percent == 50
        assert configs[3].mode == "on" and configs[3].percent == 50
