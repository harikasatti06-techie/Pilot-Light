"""Incident timeline, stored in CloudWatch Logs: one stream per incident in TIMELINE_LOG_GROUP.
Rows: {incident_id, ts (ISO with milliseconds), type, text}."""
import datetime
import json
import time

from . import logstore
from .config import TIMELINE_LOG_GROUP


def add(incident_id: str, type_: str, text: str) -> None:
    now_ms = int(time.time() * 1000)
    ts = datetime.datetime.fromtimestamp(now_ms / 1000, datetime.timezone.utc).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")
    logstore.put(TIMELINE_LOG_GROUP, incident_id,
                 [json.dumps({"ts": ts, "type": type_, "text": text})], now_ms)


def list_all(incident_id: str) -> list[dict]:
    rows = []
    for e in logstore.read_stream(TIMELINE_LOG_GROUP, incident_id):
        try:
            rows.append({"incident_id": incident_id, **json.loads(e["message"])})
        except ValueError:
            continue
    return rows
