"""Idempotent AWS setup for the event account: CloudWatch Logs groups with 1-day retention.

Run: python scripts/setup_aws.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pilotlight.config import (CHECKOUT_LOG_GROUP, CONFIG_AUDIT_LOG_GROUP,  # noqa: E402
                               INCIDENTS_LOG_GROUP, TIMELINE_LOG_GROUP)
from pilotlight.logstore import logs  # noqa: E402

GROUPS = {CHECKOUT_LOG_GROUP: 1, CONFIG_AUDIT_LOG_GROUP: 7, TIMELINE_LOG_GROUP: 7, INCIDENTS_LOG_GROUP: 7}

for name, days in GROUPS.items():
    try:
        logs.create_log_group(logGroupName=name)
        print(f"created  {name}")
    except logs.exceptions.ResourceAlreadyExistsException:
        print(f"exists   {name}")
    logs.put_retention_policy(logGroupName=name, retentionInDays=days)
print("done")
