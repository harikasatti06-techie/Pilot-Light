#!/usr/bin/env bash
# Starts the checkout service and the incident watcher. Ctrl-C stops both.
source "$(dirname "$0")/_env.sh"
trap 'kill 0' EXIT
"$PY" -m services.checkout.handler &
"$PY" -m services.incident.watcher
