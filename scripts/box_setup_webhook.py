#!/usr/bin/env python3
"""Register a Box webhook for the Incidents folder.

Run once after CDK deploy:
    python scripts/box_setup_webhook.py <webhook_url>

Or set the WEBHOOK_URL environment variable:
    WEBHOOK_URL=https://xxx.execute-api.us-east-1.amazonaws.com/prod/webhook \
        python scripts/box_setup_webhook.py
"""

import os
import sys

from box_sdk_gen.schemas import CreateWebhookTarget, CreateWebhookTargetTypeField, CreateWebhookTriggers

# Adjust path so we can import from project root
sys.path.insert(0, ".")

from pilotlight.auto_fix.box_helpers import get_client  # noqa: E402
from pilotlight.config import BOX_INCIDENTS_FOLDER_ID  # noqa: E402


def main() -> None:
    # Resolve webhook URL from CLI arg or environment
    webhook_url = None
    if len(sys.argv) > 1:
        webhook_url = sys.argv[1]
    else:
        webhook_url = os.getenv("WEBHOOK_URL")

    if not webhook_url:
        print(
            "Usage: python scripts/box_setup_webhook.py <webhook_url>\n"
            "   or: WEBHOOK_URL=<url> python scripts/box_setup_webhook.py",
            file=sys.stderr,
        )
        sys.exit(1)

    if not BOX_INCIDENTS_FOLDER_ID:
        print(
            "Error: BOX_INCIDENTS_FOLDER_ID is not set. "
            "Set it in your .env file or environment.",
            file=sys.stderr,
        )
        sys.exit(1)

    client = get_client()

    print(f"Registering webhook on folder {BOX_INCIDENTS_FOLDER_ID}...")
    print(f"  Callback URL: {webhook_url}")

    webhook = client.webhooks.create_webhook(
        target=CreateWebhookTarget(
            id=BOX_INCIDENTS_FOLDER_ID,
            type=CreateWebhookTargetTypeField.FOLDER,
        ),
        address=webhook_url,
        triggers=[CreateWebhookTriggers.FILE_UPLOADED],
    )

    print(f"Webhook created successfully.")
    print(f"  Webhook ID: {webhook.id}")
    print(f"  Target folder: {BOX_INCIDENTS_FOLDER_ID}")
    print(f"  Triggers: FILE.UPLOADED")


if __name__ == "__main__":
    main()
