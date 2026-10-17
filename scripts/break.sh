#!/usr/bin/env bash
source "$(dirname "$0")/_env.sh"
"$PY" -m pilotlight.flags on --by "${CHANGED_BY:-demo-admin}"
