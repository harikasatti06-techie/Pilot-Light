#!/usr/bin/env python3
"""Post-build script that runs inside CodeBuild after Claude Code finishes.

Reads Claude Code output, uploads artifacts to Box, and updates DynamoDB.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys

# Ensure the workspace copy of pilotlight is importable when running in
# CodeBuild where the package may live at /workspace rather than in
# site-packages.
sys.path.insert(0, "/workspace")

import boto3  # noqa: E402

from pilotlight.auto_fix.box_helpers import (  # noqa: E402
    create_subfolder,
    update_metadata,
    upload_text_file,
)
from pilotlight.config import TASKS_TABLE  # noqa: E402
from pilotlight.timeline import add as timeline_add  # noqa: E402

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)

dynamodb = boto3.resource("dynamodb")
tasks_table = dynamodb.Table(TASKS_TABLE)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_file(path: str) -> str:
    """Return the contents of *path*, or an empty string if unreadable."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except (OSError, IOError) as exc:
        logger.warning("Could not read %s: %s", path, exc)
        return ""


def _extract_pr_url(text: str) -> str | None:
    """Parse ``PR_URL=<url>`` from Claude Code output."""
    match = re.search(r"PR_URL=(https?://\S+)", text)
    return match.group(1) if match else None


def _generate_diff() -> str:
    """Run ``git diff`` in /workspace and return the output."""
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD~1"],
            capture_output=True,
            text=True,
            cwd="/workspace",
            timeout=60,
        )
        return result.stdout or "(no diff)"
    except Exception as exc:
        logger.warning("git diff failed: %s", exc)
        return f"(git diff error: {exc})"


def _collect_test_results() -> str:
    """Return pytest output if a results file exists, else run pytest."""
    results_path = "/workspace/test_results.txt"
    if os.path.isfile(results_path):
        return _read_file(results_path)

    try:
        result = subprocess.run(
            ["python", "-m", "pytest", "--tb=short", "-q"],
            capture_output=True,
            text=True,
            cwd="/workspace",
            timeout=300,
        )
        return result.stdout + "\n" + result.stderr
    except Exception as exc:
        logger.warning("pytest collection failed: %s", exc)
        return f"(pytest error: {exc})"


def _update_task(incident_id: str, task_id: str, status: str, pr_url: str = "") -> None:
    """Update the task record in DynamoDB."""
    update_expr = "SET #s = :s"
    attr_names = {"#s": "status"}
    attr_values: dict = {":s": status}

    if pr_url:
        update_expr += ", pr_url = :p"
        attr_values[":p"] = pr_url

    tasks_table.update_item(
        Key={"incident_id": incident_id, "task_id": task_id},
        UpdateExpression=update_expr,
        ExpressionAttributeNames=attr_names,
        ExpressionAttributeValues=attr_values,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    incident_id = os.environ.get("INCIDENT_ID", "")
    task_id = os.environ.get("TASK_ID", "")
    box_folder_id = os.environ.get("BOX_FOLDER_ID", "")
    claude_output_file = os.environ.get("CLAUDE_OUTPUT_FILE", "/tmp/claude_output.txt")
    build_succeeding = os.environ.get("CODEBUILD_BUILD_SUCCEEDING", "1")

    if not incident_id or not task_id:
        logger.error("INCIDENT_ID and TASK_ID must be set")
        sys.exit(1)

    claude_output = _read_file(claude_output_file)
    pr_url = _extract_pr_url(claude_output)
    build_ok = build_succeeding == "1" and bool(pr_url)

    # Ensure Box sub-folders exist
    patches_folder_id = create_subfolder(box_folder_id, "patches")
    results_folder_id = create_subfolder(box_folder_id, "test_results")

    if build_ok and pr_url:
        logger.info("PR created for TASK-%s: %s", task_id, pr_url)

        # Upload patch
        diff_content = _generate_diff()
        upload_text_file(
            patches_folder_id,
            f"TASK-{task_id}.patch",
            diff_content,
        )

        # Upload test results
        test_output = _collect_test_results()
        upload_text_file(
            results_folder_id,
            f"TASK-{task_id}_results.md",
            test_output,
        )

        # Update Box metadata
        update_metadata(box_folder_id, {
            "status": "pr_created",
            "pr_url": pr_url,
            "task_id": task_id,
        })

        # Update DynamoDB
        _update_task(incident_id, task_id, "pr_created", pr_url=pr_url)

        # Timeline
        timeline_add(
            incident_id,
            "auto-fix",
            f"PR created for TASK-{task_id}: {pr_url}",
        )

    else:
        logger.warning("Auto-fix failed for TASK-%s", task_id)

        # Upload error log
        error_content = claude_output if claude_output else "(no output captured)"
        upload_text_file(
            results_folder_id,
            f"TASK-{task_id}_error.log",
            error_content,
        )

        # Update Box metadata
        update_metadata(box_folder_id, {
            "status": "failed",
            "task_id": task_id,
        })

        # Update DynamoDB
        _update_task(incident_id, task_id, "failed")

        # Timeline
        timeline_add(
            incident_id,
            "auto-fix",
            f"Auto-fix failed for TASK-{task_id}",
        )


if __name__ == "__main__":
    main()
