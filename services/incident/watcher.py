"""Alarm evaluator. Stands in for the CloudWatch alarm + EventBridge rule, which the event
account blocks. Every 2s it counts ERROR events in the checkout log group over the alarm
window and opens an incident on the OK -> ALARM transition.

Run: python -m services.incident.watcher
Force a trigger: touch .state/force_alarm (scripts/force_alarm.sh)
"""
import datetime
import threading
import time
from pathlib import Path

from pilotlight import logstore
from pilotlight.config import (ALARM_NAME, ALARM_THRESHOLD, ALARM_WINDOW_SECONDS,
                               CHECKOUT_LOG_GROUP, STATE_DIR)
from services.incident.handler import handler

POLL_SECONDS = 2
# Logs reach filter_log_events a few seconds after they are written, so look slightly further back
INGEST_SLACK_SECONDS = 5
FORCE_FILE = Path(STATE_DIR) / "force_alarm"
STATE_FILE = Path(STATE_DIR) / "alarm_state"


def _event(reason: str) -> dict:
    return {"source": "pilotlight.watcher", "detail-type": "CloudWatch Alarm State Change",
            "detail": {"alarmName": ALARM_NAME, "state": {"value": "ALARM", "reason": reason}}}


def _fire(reason: str) -> None:
    def run():
        try:
            print(f"  incident opened: {handler(_event(reason))['incident_id']}")
        except Exception as e:
            print(f"  incident handler failed: {e}")
    threading.Thread(target=run, daemon=True).start()


def main() -> None:
    state = "OK"
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    print(f"watching {CHECKOUT_LOG_GROUP}: ALARM at >= {ALARM_THRESHOLD} errors in {ALARM_WINDOW_SECONDS}s")
    while True:
        now = time.time()
        errors = [e for e in logstore.recent(CHECKOUT_LOG_GROUP, ALARM_WINDOW_SECONDS + INGEST_SLACK_SECONDS, '"ERROR"')
                  if e["timestamp"] >= (now - ALARM_WINDOW_SECONDS - INGEST_SLACK_SECONDS) * 1000]
        forced = FORCE_FILE.exists()
        if forced:
            FORCE_FILE.unlink(missing_ok=True)
        new = "ALARM" if forced or len(errors) >= ALARM_THRESHOLD else "OK"
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        if new != state:
            print(f"{stamp} {ALARM_NAME}: {state} -> {new} ({len(errors)} errors{', forced' if forced else ''})")
            if new == "ALARM":
                _fire("forced by demo trigger" if forced else f"{len(errors)} errors in {ALARM_WINDOW_SECONDS}s")
            state = new
            STATE_FILE.write_text(state)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
