#!/usr/bin/env bash
# Backup trigger if the alarm is slow. Only produces an event if the alarm is not already in ALARM.
source "$(dirname "$0")/_env.sh"
aws cloudwatch set-alarm-state --alarm-name "$ALARM" --state-value ALARM --state-reason "demo trigger" && echo "alarm forced to ALARM"
