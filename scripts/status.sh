#!/usr/bin/env bash
# Current flag, alarm state, and the latest incident with its timeline
source "$(dirname "$0")/_env.sh"
"$PY" - <<'PY'
from pilotlight import flags, incidents, timeline
from pilotlight.config import STATE_DIR
import os
state = open(os.path.join(STATE_DIR, "alarm_state")).read() if os.path.exists(os.path.join(STATE_DIR, "alarm_state")) else "unknown (watcher not run yet)"
print(f"fail_mode: {flags.get()}\nalarm:     {state}")
inc = incidents.latest()
print(f"latest:    {inc['incident_id'] if inc else 'none'}")
if inc:
    for r in timeline.list_all(inc["incident_id"]):
        print(f"  {r['ts']}  {r['type']:<9} {r['text']}")
PY
