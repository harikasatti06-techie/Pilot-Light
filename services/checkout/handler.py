"""Demo checkout service. Fails with PaymentTimeout while fail_mode is "on".
Logs ship to CloudWatch Logs, which the incident watcher and query_logs read."""
import json
import os
import socket
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from pilotlight import flags
from pilotlight.config import CHECKOUT_LOG_GROUP, CHECKOUT_PORT
from pilotlight.logstore import BufferedShipper

shipper = BufferedShipper(CHECKOUT_LOG_GROUP, f"{socket.gethostname()}-{os.getpid()}")
_cache = {"v": "off", "t": 0.0}


def fail_mode() -> str:
    if time.time() - _cache["t"] > 1:  # re-read every second
        _cache["v"] = flags.get()
        _cache["t"] = time.time()
    return _cache["v"]


def handler(event=None, context=None):
    if fail_mode() == "on":
        shipper.log("ERROR PaymentTimeout: upstream payment provider timed out after 3000ms")
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
