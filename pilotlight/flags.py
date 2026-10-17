"""The fail_mode break switch. Value lives in a local state file; every change is audited
to CloudWatch Logs, which is what what_changed reads.

Format: 'off' or 'on:<percent>' where <percent> is 0-100
Examples: 'off', 'on:0', 'on:10', 'on:100'

CLI: python -m pilotlight.flags on|off|on:<percent> [--by NAME]
"""
import argparse
import datetime
import getpass
import json
import os
import re
from pathlib import Path

from . import logstore, metrics
from .config import CONFIG_AUDIT_LOG_GROUP, FAIL_MODE_PARAM, STATE_DIR

FLAG_FILE = Path(STATE_DIR) / "fail_mode"


def parse_fail_mode(value: str) -> tuple[str, int]:
    """Parse and validate fail_mode value.

    Returns (mode, percent) where:
    - mode is 'on' or 'off'
    - percent is 0-100

    Invalid values default to ('off', 0) and emit a config-invalid metric.
    """
    value = value.strip()

    # Valid format: 'off' or 'on' or 'on:<percent>'
    if value == "off":
        return ("off", 0)

    if value == "on":
        # Legacy format: 'on' without percent defaults to 100%
        return ("on", 100)

    # Check for 'on:<percent>' format
    match = re.match(r"^on:(\d+)$", value)
    if match:
        percent = int(match.group(1))
        if 0 <= percent <= 100:
            return ("on", percent)

    # Invalid format - emit metric and fallback to safe default
    metrics.put_metric("PilotLight", "ConfigInvalid", 1.0, "Count",
                      {"Parameter": "fail_mode", "InvalidValue": value[:50]})
    print(f"[flags] invalid fail_mode value '{value}', defaulting to 'off'")
    return ("off", 0)


def get() -> str:
    """Get raw fail_mode value from state file."""
    try:
        return FLAG_FILE.read_text().strip() or "off"
    except FileNotFoundError:
        return "off"


def get_parsed() -> tuple[str, int]:
    """Get parsed and validated fail_mode.

    Returns (mode, percent) tuple.
    Invalid values are sanitized to ('off', 0).
    """
    return parse_fail_mode(get())


def set_(value: str, by: str) -> str:
    """Set fail_mode and write an audit record. Returns the previous value.

    Value is validated before being set. Invalid values are rejected.
    """
    # Validate before setting
    mode, percent = parse_fail_mode(value)
    if mode == "off" and value not in ("off", "on:0"):
        # Value was invalid and got sanitized - don't accept it
        raise ValueError(f"Invalid fail_mode value: '{value}'. Use 'off' or 'on:<0-100>'")

    prev = get()
    FLAG_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FLAG_FILE.with_suffix(".tmp")
    tmp.write_text(value)
    os.replace(tmp, FLAG_FILE)
    logstore.put_json(CONFIG_AUDIT_LOG_GROUP, "fail_mode", {
        "parameter": FAIL_MODE_PARAM, "from": prev, "to": value, "by": by,
        "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")})
    return prev


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Set fail_mode flag. Format: 'off' or 'on:<0-100>'")
    ap.add_argument("value", help="Flag value: 'off', 'on', or 'on:<percent>' (e.g., 'on:10')")
    ap.add_argument("--by", default=getpass.getuser())
    a = ap.parse_args()

    try:
        prev = set_(a.value, a.by)
        mode, percent = parse_fail_mode(a.value)
        print(json.dumps({
            "fail_mode": a.value,
            "parsed": {"mode": mode, "percent": percent},
            "previous": prev,
            "by": a.by
        }))
    except ValueError as e:
        print(json.dumps({"error": str(e)}))
        exit(1)
