"""Demo checkout service. Fails with PaymentTimeout based on probabilistic circuit breaker.
Logs ship to CloudWatch Logs, which the incident watcher and query_logs read."""
import json
import os
import socket
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from pilotlight import flags
from pilotlight.config import CHECKOUT_LOG_GROUP, CHECKOUT_PORT
from pilotlight.logstore import BufferedShipper

# Import circuit breaker modules (handle imports gracefully in different environments)
try:
    from services.checkout.circuit_breaker import should_fail_request
    from services.checkout.config import parse_fail_mode
except ImportError:
    from checkout.circuit_breaker import should_fail_request
    from checkout.config import parse_fail_mode

shipper = BufferedShipper(CHECKOUT_LOG_GROUP, f"{socket.gethostname()}-{os.getpid()}")
_cache = {"raw": "off", "parsed": None, "t": 0.0}


def get_fail_mode_config():
    """Get and cache parsed fail_mode configuration."""
    if time.time() - _cache["t"] > 1:  # re-read every second
        raw = flags.get()
        _cache["raw"] = raw
        _cache["parsed"] = parse_fail_mode(raw)
        _cache["t"] = time.time()
    return _cache["parsed"]


def handler(event=None, context=None):
    config = get_fail_mode_config()

    # Probabilistic failure based on circuit breaker
    if should_fail_request(config):
        shipper.log(f"ERROR PaymentTimeout: upstream payment provider timed out after 3000ms (fail_mode={config.mode}:{config.percent})")
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
