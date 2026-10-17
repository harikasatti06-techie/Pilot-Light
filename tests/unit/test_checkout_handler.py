"""Unit tests for checkout handler."""
import json
from unittest.mock import MagicMock, patch

import pytest

# Import the handler module
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "services" / "checkout"))

import handler


class TestShouldFailRequest:
    """Tests for should_fail_request function."""

    def test_zero_percent_never_fails(self):
        """0% should never fail."""
        for _ in range(100):
            assert handler.should_fail_request(0) is False

    def test_hundred_percent_always_fails(self):
        """100% should always fail."""
        for _ in range(100):
            assert handler.should_fail_request(100) is True

    def test_fifty_percent_approximately_half(self):
        """50% should fail approximately half the time."""
        # Statistical test: run 1000 times, expect around 500 failures
        failures = sum(1 for _ in range(1000) if handler.should_fail_request(50))
        # Allow 10% margin of error (450-550)
        assert 450 <= failures <= 550, f"Expected ~500 failures, got {failures}"

    def test_ten_percent_approximately_one_tenth(self):
        """10% should fail approximately 10% of the time."""
        failures = sum(1 for _ in range(1000) if handler.should_fail_request(10))
        # Allow margin of error (70-130)
        assert 70 <= failures <= 130, f"Expected ~100 failures, got {failures}"


class TestGetFailConfig:
    """Tests for get_fail_config function."""

    @patch("handler.flags.get_parsed")
    @patch("handler.metrics.put_metric")
    def test_cache_invalidation(self, mock_metric, mock_get_parsed):
        """Config should be re-read after cache timeout."""
        mock_get_parsed.return_value = ("on", 50)

        # First call should read from flags
        handler._cache["t"] = 0  # Force cache miss
        mode, percent = handler.get_fail_config()
        assert mode == "on"
        assert percent == 50
        assert mock_get_parsed.call_count == 1

        # Second call within 1 second should use cache
        mode, percent = handler.get_fail_config()
        assert mode == "on"
        assert percent == 50
        assert mock_get_parsed.call_count == 1  # Still 1, not called again

    @patch("handler.flags.get_parsed")
    @patch("handler.metrics.put_metric")
    def test_warning_metric_emitted(self, mock_metric, mock_get_parsed):
        """Warning metric should be emitted when fail_mode is active."""
        mock_get_parsed.return_value = ("on", 50)
        handler._cache["t"] = 0  # Force cache miss

        handler.get_fail_config()
        mock_metric.assert_called_once_with(
            "PilotLight", "FailModeActive", 1.0, "Count",
            {"FailPercent": "50"}
        )

    @patch("handler.flags.get_parsed")
    @patch("handler.metrics.put_metric")
    def test_no_metric_when_off(self, mock_metric, mock_get_parsed):
        """No metric should be emitted when fail_mode is off."""
        mock_get_parsed.return_value = ("off", 0)
        handler._cache["t"] = 0  # Force cache miss

        handler.get_fail_config()
        mock_metric.assert_not_called()

    @patch("handler.flags.get_parsed")
    @patch("handler.metrics.put_metric")
    def test_no_metric_when_zero_percent(self, mock_metric, mock_get_parsed):
        """No metric when mode is on but percent is 0."""
        mock_get_parsed.return_value = ("on", 0)
        handler._cache["t"] = 0  # Force cache miss

        handler.get_fail_config()
        mock_metric.assert_not_called()


class TestHandler:
    """Tests for main handler function."""

    @patch("handler.shipper")
    @patch("handler.get_fail_config")
    @patch("handler.should_fail_request")
    @patch("handler.metrics.put_metric")
    def test_handler_success_when_off(self, mock_metric, mock_should_fail, mock_get_config, mock_shipper):
        """Handler should succeed when fail_mode is off."""
        mock_get_config.return_value = ("off", 0)
        mock_should_fail.return_value = False

        response = handler.handler()

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["ok"] is True
        mock_shipper.log.assert_called_with("INFO checkout ok")

    @patch("handler.shipper")
    @patch("handler.get_fail_config")
    @patch("handler.should_fail_request")
    @patch("handler.metrics.put_metric")
    def test_handler_success_when_should_not_fail(self, mock_metric, mock_should_fail, mock_get_config, mock_shipper):
        """Handler should succeed when mode is on but should_fail_request returns False."""
        mock_get_config.return_value = ("on", 10)
        mock_should_fail.return_value = False

        response = handler.handler()

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["ok"] is True

    @patch("handler.shipper")
    @patch("handler.get_fail_config")
    @patch("handler.should_fail_request")
    @patch("handler.metrics.put_metric")
    def test_handler_failure_when_should_fail(self, mock_metric, mock_should_fail, mock_get_config, mock_shipper):
        """Handler should fail when mode is on and should_fail_request returns True."""
        mock_get_config.return_value = ("on", 100)
        mock_should_fail.return_value = True

        response = handler.handler()

        assert response["statusCode"] == 502
        body = json.loads(response["body"])
        assert body["error"] == "PaymentTimeout"
        mock_shipper.log.assert_called_with("ERROR PaymentTimeout: upstream payment provider timed out after 3000ms")
        mock_metric.assert_called_with("PilotLight", "CheckoutErrors", 1.0, "Count")

    @patch("handler.shipper")
    @patch("handler.flags.FLAG_FILE")
    @patch("handler.metrics.put_metric")
    def test_handler_statistical_behavior(self, mock_metric, mock_flag_file, mock_shipper):
        """Handler should fail approximately the configured percentage of times."""
        mock_flag_file.read_text.return_value = "on:50"
        handler._cache["t"] = 0  # Force re-read

        # Use real probabilistic logic
        failures = 0
        for _ in range(100):
            response = handler.handler()
            if response["statusCode"] == 502:
                failures += 1

        # With 50%, expect around 50 failures out of 100 (allow 30-70 margin)
        assert 30 <= failures <= 70, f"Expected ~50 failures, got {failures}"


class TestIntegration:
    """Integration tests with real modules."""

    @patch("handler.flags.FLAG_FILE")
    @patch("handler.shipper")
    @patch("handler.metrics.put_metric")
    def test_end_to_end_off(self, mock_metric, mock_shipper, mock_flag_file):
        """End-to-end: fail_mode=off should never fail."""
        mock_flag_file.read_text.return_value = "off"
        handler._cache["t"] = 0  # Force re-read

        for _ in range(10):
            response = handler.handler()
            assert response["statusCode"] == 200

    @patch("handler.flags.FLAG_FILE")
    @patch("handler.shipper")
    @patch("handler.metrics.put_metric")
    def test_end_to_end_on_zero(self, mock_metric, mock_shipper, mock_flag_file):
        """End-to-end: fail_mode=on:0 should never fail."""
        mock_flag_file.read_text.return_value = "on:0"
        handler._cache["t"] = 0  # Force re-read

        for _ in range(10):
            response = handler.handler()
            assert response["statusCode"] == 200

    @patch("handler.flags.FLAG_FILE")
    @patch("handler.shipper")
    @patch("handler.metrics.put_metric")
    def test_end_to_end_on_hundred(self, mock_metric, mock_shipper, mock_flag_file):
        """End-to-end: fail_mode=on:100 should always fail."""
        mock_flag_file.read_text.return_value = "on:100"
        handler._cache["t"] = 0  # Force re-read

        for _ in range(10):
            response = handler.handler()
            assert response["statusCode"] == 502

    @patch("handler.flags.FLAG_FILE")
    @patch("handler.shipper")
    @patch("handler.metrics.put_metric")
    def test_end_to_end_invalid_value_defaults_to_off(self, mock_metric, mock_shipper, mock_flag_file):
        """End-to-end: invalid fail_mode value should default to off and emit metric."""
        mock_flag_file.read_text.return_value = "invalid-value"
        handler._cache["t"] = 0  # Force re-read

        response = handler.handler()
        assert response["statusCode"] == 200
        # Should have emitted config-invalid metric
        metric_calls = [call for call in mock_metric.call_args_list
                       if call[0][1] == "ConfigInvalid"]
        assert len(metric_calls) > 0
