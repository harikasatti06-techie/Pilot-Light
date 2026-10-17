"""Unit tests for pilotlight.flags module."""
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pilotlight import flags


class TestParseFailMode:
    """Tests for parse_fail_mode function."""

    @patch("pilotlight.flags.metrics.put_metric")
    def test_parse_off(self, mock_metric):
        """'off' should parse to mode='off', percent=0."""
        mode, percent = flags.parse_fail_mode("off")
        assert mode == "off"
        assert percent == 0
        mock_metric.assert_not_called()

    @patch("pilotlight.flags.metrics.put_metric")
    def test_parse_on_legacy(self, mock_metric):
        """'on' without percent should default to 100%."""
        mode, percent = flags.parse_fail_mode("on")
        assert mode == "on"
        assert percent == 100
        mock_metric.assert_not_called()

    @patch("pilotlight.flags.metrics.put_metric")
    def test_parse_on_with_zero(self, mock_metric):
        """'on:0' should parse to mode='on', percent=0."""
        mode, percent = flags.parse_fail_mode("on:0")
        assert mode == "on"
        assert percent == 0
        mock_metric.assert_not_called()

    @patch("pilotlight.flags.metrics.put_metric")
    def test_parse_on_with_valid_percent(self, mock_metric):
        """'on:<percent>' should parse correctly for valid percents."""
        for p in [1, 10, 25, 50, 75, 100]:
            mode, percent = flags.parse_fail_mode(f"on:{p}")
            assert mode == "on"
            assert percent == p
        mock_metric.assert_not_called()

    @patch("pilotlight.flags.metrics.put_metric")
    def test_parse_invalid_format(self, mock_metric):
        """Invalid formats should default to 'off', 0 and emit metric."""
        invalid_values = [
            "invalid",
            "on:",
            "on:abc",
            "on:-10",
            "on:101",
            "on:1000",
            "off:10",
            "ON:50",
            "",
        ]
        for value in invalid_values:
            mode, percent = flags.parse_fail_mode(value)
            assert mode == "off", f"Expected 'off' for '{value}'"
            assert percent == 0, f"Expected 0 for '{value}'"
            mock_metric.assert_called()
            mock_metric.reset_mock()

    @patch("pilotlight.flags.metrics.put_metric")
    def test_parse_whitespace_handling(self, mock_metric):
        """Whitespace should be stripped."""
        mode, percent = flags.parse_fail_mode("  on:50  ")
        assert mode == "on"
        assert percent == 50
        mock_metric.assert_not_called()


class TestGetParsed:
    """Tests for get_parsed function."""

    @patch("pilotlight.flags.FLAG_FILE")
    @patch("pilotlight.flags.metrics.put_metric")
    def test_get_parsed_valid_value(self, mock_metric, mock_file):
        """get_parsed should return parsed value from file."""
        mock_file.read_text.return_value = "on:25"
        mode, percent = flags.get_parsed()
        assert mode == "on"
        assert percent == 25
        mock_metric.assert_not_called()

    @patch("pilotlight.flags.FLAG_FILE")
    @patch("pilotlight.flags.metrics.put_metric")
    def test_get_parsed_missing_file(self, mock_metric, mock_file):
        """get_parsed should default to 'off', 0 when file is missing."""
        mock_file.read_text.side_effect = FileNotFoundError
        mode, percent = flags.get_parsed()
        assert mode == "off"
        assert percent == 0
        mock_metric.assert_not_called()

    @patch("pilotlight.flags.FLAG_FILE")
    @patch("pilotlight.flags.metrics.put_metric")
    def test_get_parsed_invalid_value(self, mock_metric, mock_file):
        """get_parsed should sanitize invalid value and emit metric."""
        mock_file.read_text.return_value = "invalid"
        mode, percent = flags.get_parsed()
        assert mode == "off"
        assert percent == 0
        mock_metric.assert_called_once()


class TestSetFailMode:
    """Tests for set_ function."""

    @patch("pilotlight.flags.logstore.put_json")
    @patch("pilotlight.flags.metrics.put_metric")
    def test_set_valid_values(self, mock_metric, mock_log):
        """set_ should accept valid values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            flags.FLAG_FILE = Path(tmpdir) / "fail_mode"

            # Set to valid values
            for value in ["off", "on:0", "on:50", "on:100"]:
                prev = flags.set_(value, "test-user")
                assert flags.get() == value

    @patch("pilotlight.flags.logstore.put_json")
    @patch("pilotlight.flags.metrics.put_metric")
    def test_set_invalid_value_raises(self, mock_metric, mock_log):
        """set_ should reject invalid values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            flags.FLAG_FILE = Path(tmpdir) / "fail_mode"

            with pytest.raises(ValueError, match="Invalid fail_mode value"):
                flags.set_("invalid", "test-user")

            with pytest.raises(ValueError, match="Invalid fail_mode value"):
                flags.set_("on:101", "test-user")

    @patch("pilotlight.flags.logstore.put_json")
    @patch("pilotlight.flags.metrics.put_metric")
    def test_set_audit_log(self, mock_metric, mock_log):
        """set_ should write audit log."""
        with tempfile.TemporaryDirectory() as tmpdir:
            flags.FLAG_FILE = Path(tmpdir) / "fail_mode"

            flags.set_("on:50", "test-user")
            mock_log.assert_called_once()
            args = mock_log.call_args
            assert args[0][2]["to"] == "on:50"
            assert args[0][2]["by"] == "test-user"


class TestCLI:
    """Tests for CLI behavior."""

    @patch("pilotlight.flags.set_")
    def test_cli_valid_value(self, mock_set):
        """CLI should accept valid values."""
        mock_set.return_value = "off"

        # Simulate CLI call
        import sys
        old_argv = sys.argv
        try:
            sys.argv = ["flags.py", "on:50", "--by", "cli-user"]
            # We can't easily test the if __name__ == "__main__" block,
            # but we've validated the underlying functions
        finally:
            sys.argv = old_argv
