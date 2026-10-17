#!/usr/bin/env bash
# Manual reset between rehearsals
source "$(dirname "$0")/_env.sh"
"$PY" -m pilotlight.flags off --by "${CHANGED_BY:-demo-admin}"
