#!/usr/bin/env bash
# Backup trigger: the watcher opens an incident on its next poll if the alarm is currently OK.
source "$(dirname "$0")/_env.sh"
mkdir -p .state && touch .state/force_alarm && echo "force_alarm requested"
