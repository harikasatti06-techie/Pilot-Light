"""Unit tests for the checkout service handler."""
import json
from unittest.mock import patch

from services.checkout.handler import handler


class TestCheckoutHandler:
    """Verify checkout returns 200 or 502 based on fail_mode flag."""

    @patch("services.checkout.handler.fail_mode", return_value="off")
    @patch("services.checkout.handler.shipper")
    def test_returns_200_when_flag_off(self, mock_shipper, mock_flag):
        result = handler()
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["ok"] is True

    @patch("services.checkout.handler.fail_mode", return_value="on")
    @patch("services.checkout.handler.shipper")
    def test_returns_502_when_flag_on(self, mock_shipper, mock_flag):
        result = handler()
        assert result["statusCode"] == 502
        body = json.loads(result["body"])
        assert "PaymentTimeout" in body["error"]

    @patch("services.checkout.handler.fail_mode", return_value="on")
    @patch("services.checkout.handler.shipper")
    def test_logs_error_on_failure(self, mock_shipper, mock_flag):
        handler()
        mock_shipper.log.assert_called_once()
        assert "PaymentTimeout" in mock_shipper.log.call_args[0][0]
