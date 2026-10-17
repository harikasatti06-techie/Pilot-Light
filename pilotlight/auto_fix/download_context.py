#!/usr/bin/env python3
"""Download incident context files from Box into /workspace/context/.

Runs during the CodeBuild pre_build phase so that Claude Code has access
to postmortem, transcript, timeline, and briefing documents.
"""

from __future__ import annotations

import logging
import os
import sys

# Ensure pilotlight is importable from the workspace checkout.
sys.path.insert(0, "/workspace")

from pilotlight.auto_fix.box_helpers import download_file_content, get_client  # noqa: E402

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)

# Files we want to pull into the build context.
CONTEXT_FILES = frozenset({
    "postmortem.md",
    "transcript.md",
    "timeline.md",
    "briefing.md",
})

CONTEXT_DIR = "/workspace/context"


def main() -> None:
    incident_id = os.environ.get("INCIDENT_ID", "")
    folder_id = os.environ.get("BOX_FOLDER_ID", "")

    if not folder_id:
        logger.warning("BOX_FOLDER_ID not set -- skipping context download")
        return

    os.makedirs(CONTEXT_DIR, exist_ok=True)

    client = get_client()
    items = client.folders.get_folder_items(folder_id)

    downloaded = 0
    for item in items.entries:
        if item.name in CONTEXT_FILES:
            try:
                content = download_file_content(item.id)
                dest = os.path.join(CONTEXT_DIR, item.name)
                with open(dest, "w", encoding="utf-8") as fh:
                    fh.write(content)
                logger.info("Downloaded %s", item.name)
                downloaded += 1
            except Exception:
                logger.exception("Failed to download %s", item.name)

    logger.info(
        "Downloaded %d/%d context files for incident %s",
        downloaded,
        len(CONTEXT_FILES),
        incident_id,
    )


if __name__ == "__main__":
    main()
