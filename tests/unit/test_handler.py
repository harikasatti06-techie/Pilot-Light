"""Unit tests for services/checkout/handler.py"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add services and pilotlight to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "services"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from checkout.config import FailModeConfig


class TestHandlerWithCircuitBreaker:
    """Integration tests for handler with circuit breaker."""

    @patch('pilotlight.logstore.BufferedShipper')
    @patch('pilotlight.flags.get')
    def test_handler_when_fail_mode_off(self, mock_flags_get, mock_shipper_class):
        """Test handler returns 200 when fail_mode is off."""
        # Mock setup
        mock_flags_get.return_value = "off"
        mock_shipper = MagicMock()
        mock_shipper_class.return_value = mock_shipper

        # Import handler after mocking
        from checkout.handler import handler

        # Call handler
        response = handler()

        # Verify response
        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body == {"ok": True}

        # Verify log was called
        mock_shipper.log.assert_called_once()
        assert "INFO checkout ok" in mock_shipper.log.call_args[0][0]

    @patch('pilotlight.logstore.BufferedShipper')
    @patch('pilotlight.flags.get')
    def test_handler_when_fail_mode_on_100(self, mock_flags_get, mock_shipper_class):
        """Test handler returns 502 consistently when fail_mode is on:100."""
        # Mock setup
        mock_flags_get.return_value = "on:100"
        mock_shipper = MagicMock()
        mock_shipper_class.return_value = mock_shipper

        # Import handler after mocking (need fresh import)
        import importlib
        import checkout.handler
        importlib.reload(checkout.handler)
        from checkout.handler import handler

        # Call handler multiple times - should always fail at 100%
        for _ in range(10):
            response = handler()
            assert response["statusCode"] == 502
            body = json.loads(response["body"])
            assert body == {"error": "PaymentTimeout"}

        # Verify error logs were called
        assert mock_shipper.log.call_count == 10
        for call in mock_shipper.log.call_args_list:
            assert "ERROR PaymentTimeout" in call[0][0]
            assert "fail_mode=on:100" in call[0][0]

    @patch('pilotlight.logstore.BufferedShipper')
    @patch('pilotlight.flags.get')
    def test_handler_when_fail_mode_on_0(self, mock_flags_get, mock_shipper_class):
        """Test handler never fails when fail_mode is on:0."""
        # Mock setup
        mock_flags_get.return_value = "on:0"
        mock_shipper = MagicMock()
        mock_shipper_class.return_value = mock_shipper

        # Import handler after mocking
        import importlib
        import checkout.handler
        importlib.reload(checkout.handler)
        from checkout.handler import handler

        # Call handler multiple times - should never fail at 0%
        for _ in range(20):
            response = handler()
            assert response["statusCode"] == 200
            body = json.loads(response["body"])
            assert body == {"ok": True}

    @patch('pilotlight.logstore.BufferedShipper')
    @patch('pilotlight.flags.get')
    def test_handler_probabilistic_behavior_50_percent(self, mock_flags_get, mock_shipper_class):
        """Test handler fails approximately 50% of requests with on:50."""
        # Mock setup
        mock_flags_get.return_value = "on:50"
        mock_shipper = MagicMock()
        mock_shipper_class.return_value = mock_shipper

        # Import handler after mocking
        import importlib
        import checkout.handler
        importlib.reload(checkout.handler)
        from checkout.handler import handler

        # Call handler many times
        failures = 0
        successes = 0
        for _ in range(100):
            response = handler()
            if response["statusCode"] == 502:
                failures += 1
            elif response["statusCode"] == 200:
                successes += 1

        # Should have approximately 50% failures (allow 20% margin = 30-70)
        assert 30 <= failures <= 70, f"Expected ~50 failures, got {failures}"
        assert 30 <= successes <= 70, f"Expected ~50 successes, got {successes}"

    @patch('pilotlight.logstore.BufferedShipper')
    @patch('pilotlight.flags.get')
    def test_handler_with_legacy_on_format(self, mock_flags_get, mock_shipper_class):
        """Test handler with legacy 'on' format (should be 100% failures)."""
        # Mock setup
        mock_flags_get.return_value = "on"  # Legacy format
        mock_shipper = MagicMock()
        mock_shipper_class.return_value = mock_shipper

        # Import handler after mocking
        import importlib
        import checkout.handler
        importlib.reload(checkout.handler)
        from checkout.handler import handler

        # Call handler - should always fail (100%)
        for _ in range(10):
            response = handler()
            assert response["statusCode"] == 502

    @patch('pilotlight.logstore.BufferedShipper')
    @patch('pilotlight.flags.get')
    def test_handler_with_invalid_fail_mode_defaults_to_off(self, mock_flags_get, mock_shipper_class, capsys):
        """Test handler defaults to off for invalid fail_mode values."""
        # Mock setup
        mock_flags_get.return_value = "invalid:value"
        mock_shipper = MagicMock()
        mock_shipper_class.return_value = mock_shipper

        # Import handler after mocking
        import importlib
        import checkout.handler
        importlib.reload(checkout.handler)
        from checkout.handler import handler

        # Call handler - should succeed (defaults to off)
        response = handler()
        assert response["statusCode"] == 200

        # Verify error was logged about invalid config
        captured = capsys.readouterr()
        assert "Invalid fail_mode value" in captured.out
