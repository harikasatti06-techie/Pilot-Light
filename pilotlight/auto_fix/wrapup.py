"""Wrap-up Lambda for the Pilot Light Auto-Fix pipeline.

Triggered by EventBridge when CodeBuild builds complete.  Checks whether
ALL builds for an incident are finished, then generates a summary in Box
and creates a review task for the on-call reviewer.
"""

from __future__ import annotations

import json
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key

from pilotlight.config import (
    TASKS_TABLE,
    INCIDENTS_TABLE,
    BOX_REVIEWER_LOGIN,
    BOX_INCIDENTS_FOLDER_ID,
)
from pilotlight.auto_fix.box_helpers import (
    upload_text_file,
    ai_text_gen,
    create_review_task,
    add_collaboration,
    update_metadata,
    download_file_content,
    query_metadata,
)
from pilotlight.timeline import add as timeline_add

dynamodb = boto3.resource("dynamodb")
tasks_table = dynamodb.Table(TASKS_TABLE)
incidents_table = dynamodb.Table(INCIDENTS_TABLE)

TERMINAL_STATUSES = {"pr_created", "test_failed", "build_failed", "failed"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _env_var(env_vars: list[dict[str, str]], name: str) -> str | None:
    """Extract a variable from the CodeBuild environment-variables-override list."""
    for var in env_vars:
        if var.get("name") == name:
            return var.get("value")
    return None


def _get_tasks_for_incident(incident_id: str) -> list[dict[str, Any]]:
    """Return all tasks belonging to *incident_id*."""
    response = tasks_table.query(
        KeyConditionExpression=Key("incident_id").eq(incident_id),
    )
    items = response["Items"]
    # Handle pagination
    while "LastEvaluatedKey" in response:
        response = tasks_table.query(
            KeyConditionExpression=Key("incident_id").eq(incident_id),
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        items.extend(response["Items"])
    return items


def _build_manual_summary(
    incident_id: str,
    tasks: list[dict[str, Any]],
    pr_count: int,
    failed_count: int,
    pr_urls: list[str],
) -> str:
    """Build a markdown summary without Box AI."""
    lines: list[str] = [
        f"# Auto-Fix Summary: {incident_id}",
        "",
        f"**Tasks extracted:** {len(tasks)}  ",
        f"**Pull requests created:** {pr_count}  ",
        f"**Tasks failed:** {failed_count}  ",
        "",
    ]

    if pr_urls:
        lines.append("## Pull Requests")
        lines.append("")
        for url in pr_urls:
            lines.append(f"- {url}")
        lines.append("")

    lines.append("## Task Details")
    lines.append("")
    lines.append("| Task | Status | PR |")
    lines.append("|------|--------|----|")
    for task in tasks:
        tid = task.get("task_id", "unknown")
        status = task.get("status", "unknown")
        pr = task.get("pr_url", "-")
        lines.append(f"| {tid} | {status} | {pr} |")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Process a CodeBuild State Change event from EventBridge."""

    detail = event.get("detail", {})
    build_status: str = detail.get("build-status", "UNKNOWN")
    env_vars: list[dict[str, str]] = detail.get("environment-variables-override", [])

    # ------------------------------------------------------------------
    # Step 1 - Extract identifiers
    # ------------------------------------------------------------------
    incident_id = _env_var(env_vars, "INCIDENT_ID")
    task_id = _env_var(env_vars, "TASK_ID")

    if not incident_id or not task_id:
        print(f"[wrapup] Missing INCIDENT_ID or TASK_ID in event: {json.dumps(detail)}")
        return {"error": "missing_ids"}

    print(f"[wrapup] incident={incident_id} task={task_id} build_status={build_status}")

    # ------------------------------------------------------------------
    # Step 2 - Update task status on build failure
    # ------------------------------------------------------------------
    if build_status == "FAILED":
        try:
            tasks_table.update_item(
                Key={"incident_id": incident_id, "task_id": task_id},
                UpdateExpression="SET #s = :s",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":s": "build_failed"},
            )
            timeline_add(
                incident_id,
                "auto_fix",
                f"Build failed for task {task_id}",
            )
            print(f"[wrapup] Marked task {task_id} as build_failed")
        except Exception as exc:
            print(f"[wrapup] Error updating task {task_id}: {exc}")

    # ------------------------------------------------------------------
    # Step 3 - Check if all tasks are terminal
    # ------------------------------------------------------------------
    tasks = _get_tasks_for_incident(incident_id)
    total_count = len(tasks)

    if total_count == 0:
        print(f"[wrapup] No tasks found for {incident_id}")
        return {"incident_id": incident_id, "status": "no_tasks"}

    all_done = all(t.get("status") in TERMINAL_STATUSES for t in tasks)
    if not all_done:
        pending = [
            t["task_id"]
            for t in tasks
            if t.get("status") not in TERMINAL_STATUSES
        ]
        print(f"[wrapup] Not all tasks complete for {incident_id}. Pending: {pending}")
        return {"incident_id": incident_id, "status": "pending", "pending_tasks": pending}

    print(f"[wrapup] All {total_count} tasks complete for {incident_id}")

    # ------------------------------------------------------------------
    # Step 4 - Collect results
    # ------------------------------------------------------------------
    pr_urls: list[str] = []
    pr_count = 0
    failed_count = 0

    for task in tasks:
        status = task.get("status")
        if status == "pr_created":
            pr_count += 1
            pr_url = task.get("pr_url")
            if pr_url:
                pr_urls.append(pr_url)
        elif status in {"test_failed", "build_failed", "failed"}:
            failed_count += 1

    # Fetch the incident record for the Box folder ID
    box_folder_id: str | None = None
    try:
        incident_resp = incidents_table.get_item(Key={"incident_id": incident_id})
        incident_item = incident_resp.get("Item", {})
        box_folder_id = incident_item.get("box_folder_id")
    except Exception as exc:
        print(f"[wrapup] Error fetching incident record: {exc}")

    if not box_folder_id:
        print(f"[wrapup] No box_folder_id for {incident_id}, using root incidents folder")
        box_folder_id = BOX_INCIDENTS_FOLDER_ID

    # ------------------------------------------------------------------
    # Step 5 - Generate summary via Box AI
    # ------------------------------------------------------------------
    summary_text: str | None = None

    try:
        # Find the postmortem file in the incident folder
        postmortem_files = query_metadata(
            template_key="pilotlightMetadata",
            ancestor_folder_id=box_folder_id,
            query="type = :type",
            params={":type": "postmortem"},
        )
        if postmortem_files:
            postmortem_file_id = postmortem_files[0].get("id")
            if postmortem_file_id:
                pr_list = ", ".join(pr_urls) if pr_urls else "none"
                prompt = (
                    f"Generate a concise auto-fix summary report. "
                    f"{total_count} tasks were extracted. "
                    f"{pr_count} pull requests were created: {pr_list}. "
                    f"{failed_count} tasks failed. "
                    f"Include a table of tasks with their status and PR links. "
                    f"Format as markdown."
                )
                summary_text = ai_text_gen(postmortem_file_id, prompt)
                print("[wrapup] Generated summary via Box AI")
        else:
            print("[wrapup] No postmortem file found in Box folder")
    except Exception as exc:
        print(f"[wrapup] Box AI text gen failed, falling back to manual summary: {exc}")

    if not summary_text:
        summary_text = _build_manual_summary(
            incident_id, tasks, pr_count, failed_count, pr_urls,
        )
        print("[wrapup] Using manually generated summary")

    # ------------------------------------------------------------------
    # Step 6 - Upload pr_summary.md to Box
    # ------------------------------------------------------------------
    pr_summary_file_id: str | None = None
    try:
        pr_summary_file_id = upload_text_file(
            box_folder_id,
            "pr_summary.md",
            summary_text,
        )
        print(f"[wrapup] Uploaded pr_summary.md -> file_id={pr_summary_file_id}")
    except Exception as exc:
        print(f"[wrapup] Failed to upload pr_summary.md: {exc}")

    if pr_summary_file_id:
        try:
            update_metadata(
                pr_summary_file_id,
                "pilotlightMetadata",
                [
                    {"op": "add", "path": "/type", "value": "summary"},
                    {"op": "add", "path": "/incident_id", "value": incident_id},
                    {"op": "add", "path": "/status", "value": "auto_fix_complete"},
                ],
            )
        except Exception as exc:
            print(f"[wrapup] Failed to set metadata on pr_summary.md: {exc}")

    # ------------------------------------------------------------------
    # Step 7 - Create Box review task
    # ------------------------------------------------------------------
    if pr_summary_file_id:
        try:
            create_review_task(
                file_id=pr_summary_file_id,
                message=f"Review auto-fix PRs for {incident_id}",
                reviewer_login=BOX_REVIEWER_LOGIN,
            )
            print(f"[wrapup] Created review task for {BOX_REVIEWER_LOGIN}")
        except Exception as exc:
            print(f"[wrapup] Failed to create review task: {exc}")

    # ------------------------------------------------------------------
    # Step 8 - Add collaboration
    # ------------------------------------------------------------------
    try:
        add_collaboration(
            folder_id=box_folder_id,
            login=BOX_REVIEWER_LOGIN,
            role="editor",
        )
        print(f"[wrapup] Added collaboration for {BOX_REVIEWER_LOGIN}")
    except Exception as exc:
        print(f"[wrapup] Failed to add collaboration: {exc}")

    # ------------------------------------------------------------------
    # Step 9 - Update incident status
    # ------------------------------------------------------------------
    try:
        incidents_table.update_item(
            Key={"incident_id": incident_id},
            UpdateExpression="SET #s = :s",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": "auto_fix_complete"},
        )
        print(f"[wrapup] Updated incident {incident_id} to auto_fix_complete")
    except Exception as exc:
        print(f"[wrapup] Failed to update incident status: {exc}")

    try:
        timeline_add(
            incident_id,
            "auto_fix",
            f"Auto-fix complete: {pr_count} PRs created out of {total_count} tasks",
        )
    except Exception as exc:
        print(f"[wrapup] Failed to add timeline entry: {exc}")

    # ------------------------------------------------------------------
    # Step 10 - Return result
    # ------------------------------------------------------------------
    result = {
        "incident_id": incident_id,
        "status": "auto_fix_complete",
        "prs_created": pr_count,
        "tasks_total": total_count,
        "tasks_failed": failed_count,
    }
    print(f"[wrapup] Done: {json.dumps(result)}")
    return result
