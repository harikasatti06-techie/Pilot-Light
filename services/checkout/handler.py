"""Demo checkout service. Fails with PaymentTimeout while fail_mode is "on".
Logs ship to CloudWatch Logs, which the incident watcher and query_logs read."""
import json
import os
import random
import socket
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from pilotlight import flags
from pilotlight.config import CHECKOUT_LOG_GROUP, CHECKOUT_PORT
from pilotlight.logstore import BufferedShipper
from pilotlight import metrics

shipper = BufferedShipper(CHECKOUT_LOG_GROUP, f"{socket.gethostname()}-{os.getpid()}")
_cache = {"mode": "off", "percent": 0, "t": 0.0}


def get_fail_config() -> tuple[str, int]:
    """Get cached fail_mode config. Returns (mode, percent)."""
    if time.time() - _cache["t"] > 1:  # re-read every second
        mode, percent = flags.get_parsed()
        _cache["mode"] = mode
        _cache["percent"] = percent
        _cache["t"] = time.time()

        # Emit warning metric when fail_mode is active with non-zero percent
        if mode == "on" and percent > 0:
            metrics.put_metric("PilotLight", "FailModeActive", 1.0, "Count",
                             {"FailPercent": str(percent)})
    return _cache["mode"], _cache["percent"]


def should_fail_request(percent: int) -> bool:
    """Probabilistic circuit breaker. Returns True with probability percent/100."""
    if percent <= 0:
        return False
    if percent >= 100:
        return True
    return random.random() * 100 < percent


def handler(event=None, context=None):
    mode, percent = get_fail_config()

    if mode == "on" and should_fail_request(percent):
        shipper.log("ERROR PaymentTimeout: upstream payment provider timed out after 3000ms")
        metrics.put_metric("PilotLight", "CheckoutErrors", 1.0, "Count")
        return {"statusCode": 502, "body": json.dumps({"error": "PaymentTimeout"})}

    shipper.log("INFO checkout ok")
    return {"statusCode": 200, "body": json.dumps({"ok": True})}


class _Http(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?")[0] != "/checkout":
            self.send_response(404); self.end_headers(); return
        r = handler()
        body = r["body"].encode()
        self.send_response(r["statusCode"])
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep the terminal quiet; traffic.sh prints status
        pass


if __name__ == "__main__":
    print(f"checkout-api listening on http://localhost:{CHECKOUT_PORT}/checkout, logs -> {CHECKOUT_LOG_GROUP}")
    ThreadingHTTPServer(("0.0.0.0", CHECKOUT_PORT), _Http).serve_forever()
