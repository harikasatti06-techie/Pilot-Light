"""Intake Lambda for the Pilot Light Auto-Fix pipeline.

Triggered by a Box Webhook (FILE.UPLOADED on postmortem.md) via API Gateway,
or invoked directly with an incident_id for testing.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import boto3

from pilotlight.config import (
    AWS_REGION,
    BOX_INCIDENTS_FOLDER_ID,
    BOX_RUNBOOKS_FOLDER_ID,
    CONFIDENCE_THRESHOLD,
    DISPATCHER_FUNCTION_NAME,
    INCIDENTS_TABLE,
    TASKS_TABLE,
    TEXT_MODEL_ID,
)
from pilotlight.auto_fix.box_helpers import (
    ai_ask_multi,
    ai_extract_structured,
    apply_metadata,
    create_subfolder,
    download_file_content,
    get_client,
    query_metadata,
    upload_text_file,
)
from pilotlight.timeline import add as timeline_add

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
incidents_table = dynamodb.Table(INCIDENTS_TABLE)
tasks_table = dynamodb.Table(TASKS_TABLE)
lambda_client = boto3.client("lambda", region_name=AWS_REGION)
bedrock_client = boto3.client("bedrock-runtime", region_name=AWS_REGION)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_file_in_folder(folder_id: str, file_name: str) -> str | None:
    """List items in a Box folder and return the file_id matching *file_name*."""
    client = get_client()
    folder = client.folder(folder_id)
    for item in folder.get_items():
        if item.type == "file" and item.name == file_name:
            return item.id
    return None


def _parse_webhook_event(event: dict[str, Any]) -> str | None:
    """Extract file_id from a Box webhook payload forwarded by API Gateway."""
    body = event.get("body", "")
    if isinstance(body, str):
        body = json.loads(body)
    source = body.get("source", {})
    file_name = source.get("name", "")
    if file_name != "postmortem.md":
        print(f"[intake] Ignoring upload of non-postmortem file: {file_name}")
        return None
    return source.get("id")


def _get_incident_by_file(file_id: str) -> dict[str, Any] | None:
    """Scan incidents table for a record whose box_folder contains *file_id*."""
    # The postmortem lives inside the incident folder, so walk up one level.
    client = get_client()
    file_info = client.file(file_id).get()
    folder_id = file_info.parent.id

    resp = incidents_table.scan(
        FilterExpression="box_folder_id = :fid",
        ExpressionAttributeValues={":fid": folder_id},
    )
    items = resp.get("Items", [])
    return items[0] if items else None


def _bedrock_extract_tasks(
    postmortem_text: str,
    ai_analysis: str,
    incident_id: str,
) -> list[dict[str, Any]]:
    """Fallback: use Bedrock Converse API to extract structured tasks."""
    prompt = (
        "You are a senior SRE. Given an incident postmortem and an AI root-cause "
        "analysis, extract concrete code-fix tasks as JSON.\n\n"
        "Return ONLY valid JSON matching this schema:\n"
        '{"tasks": [{"task_id": "TASK-001", "title": "...", "type": "code_fix", '
        '"description": "...", "files_to_examine": [...], '
        '"acceptance_criteria": "...", "priority": "P1", '
        '"root_cause_link": "...", "confidence_score": 0.0}]}\n\n'
        f"## Postmortem\n{postmortem_text}\n\n"
        f"## AI Analysis\n{ai_analysis}"
    )

    response = bedrock_client.converse(
        modelId=TEXT_MODEL_ID,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 4096, "temperature": 0.2},
    )

    output_text = response["output"]["message"]["content"][0]["text"]
    # Strip markdown fences if present
    if output_text.strip().startswith("```"):
        lines = output_text.strip().splitlines()
        lines = [l for l in lines if not l.strip().startswith("```")]
        output_text = "\n".join(lines)

    parsed = json.loads(output_text)
    tasks = parsed.get("tasks", [])

    # Assign sequential task_ids if missing
    for i, task in enumerate(tasks, start=1):
        if not task.get("task_id"):
            task["task_id"] = f"TASK-{i:03d}"
        task.setdefault("confidence_score", 0.8)

    return tasks


def _build_plan_markdown(
    incident_id: str,
    alarm_name: str,
    ai_analysis: str,
    citations: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
) -> str:
    """Render auto_fix_plan.md content."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines = [
        f"# Auto-Fix Plan: {incident_id}",
        f"**Alarm:** {alarm_name}",
        f"**Generated:** {now}",
        "",
        "## AI Root-Cause Analysis",
        ai_analysis,
        "",
    ]

    if citations:
        lines.append("### Citations")
        for cit in citations:
            lines.append(f"- {cit}")
        lines.append("")

    lines.append("## Extracted Tasks")
    for task in tasks:
        lines.append(f"### {task['task_id']}: {task.get('title', 'Untitled')}")
        lines.append(f"- **Type:** {task.get('type', 'code_fix')}")
        lines.append(f"- **Priority:** {task.get('priority', 'P2')}")
        lines.append(f"- **Confidence:** {task.get('confidence_score', 'N/A')}")
        lines.append(f"- **Description:** {task.get('description', '')}")
        files = task.get("files_to_examine", [])
        if files:
            lines.append(f"- **Files:** {', '.join(files)}")
        lines.append(f"- **Acceptance Criteria:** {task.get('acceptance_criteria', '')}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point."""
    print(f"[intake] Event received: {json.dumps(event, default=str)[:500]}")

    # ------------------------------------------------------------------
    # Input handling
    # ------------------------------------------------------------------
    incident_record: dict[str, Any] | None = None

    if "body" in event:
        # API Gateway / Box webhook path
        file_id = _parse_webhook_event(event)
        if file_id is None:
            return {"statusCode": 200, "body": "Ignored: not a postmortem.md upload"}
        incident_record = _get_incident_by_file(file_id)
        if incident_record is None:
            print(f"[intake] No incident found for file {file_id}")
            return {"statusCode": 404, "body": "Incident not found for uploaded file"}

    elif "incident_id" in event:
        # Direct / test invocation
        incident_id = event["incident_id"]
        resp = incidents_table.get_item(Key={"incident_id": incident_id})
        incident_record = resp.get("Item")
        if incident_record is None:
            print(f"[intake] Incident {incident_id} not found in DynamoDB")
            return {"statusCode": 404, "body": f"Incident {incident_id} not found"}

    else:
        return {"statusCode": 400, "body": "Missing body or incident_id in event"}

    incident_id: str = incident_record["incident_id"]
    box_folder_id: str = incident_record["box_folder_id"]
    alarm_name: str = incident_record.get("alarm_name", "unknown")
    runbook_file_id: str | None = incident_record.get("runbook_file_id")

    print(f"[intake] Processing incident {incident_id}, folder {box_folder_id}")
    timeline_add(incident_id, "auto_fix", "Intake started: analyzing postmortem")

    # ------------------------------------------------------------------
    # Step 1: Get incident context
    # ------------------------------------------------------------------
    postmortem_file_id = _find_file_in_folder(box_folder_id, "postmortem.md")
    transcript_file_id = _find_file_in_folder(box_folder_id, "transcript.md")

    if postmortem_file_id is None:
        msg = f"postmortem.md not found in folder {box_folder_id}"
        print(f"[intake] {msg}")
        return {"statusCode": 404, "body": msg}

    postmortem_text = download_file_content(postmortem_file_id)
    transcript_text: str | None = None
    if transcript_file_id:
        try:
            transcript_text = download_file_content(transcript_file_id)
        except Exception as exc:
            print(f"[intake] Could not download transcript: {exc}")

    print(f"[intake] Downloaded postmortem ({len(postmortem_text)} chars)")

    # ------------------------------------------------------------------
    # Step 2: Cross-incident learning
    # ------------------------------------------------------------------
    past_postmortem_ids: list[str] = []
    try:
        past_incidents = query_metadata(
            template_key="incident",
            ancestor_folder_id=BOX_INCIDENTS_FOLDER_ID,
            query="alarm_name = :alarm",
            params={":alarm": alarm_name},
        )
        # Exclude current incident, limit to 3 most recent
        for item in past_incidents:
            item_folder_id = item.get("id", "")
            if item_folder_id == box_folder_id:
                continue
            pm_id = _find_file_in_folder(item_folder_id, "postmortem.md")
            if pm_id:
                past_postmortem_ids.append(pm_id)
            if len(past_postmortem_ids) >= 3:
                break
        print(f"[intake] Found {len(past_postmortem_ids)} past postmortems for alarm {alarm_name}")
    except Exception as exc:
        print(f"[intake] Cross-incident query failed, continuing without: {exc}")

    # ------------------------------------------------------------------
    # Step 3: Box AI Analysis
    # ------------------------------------------------------------------
    ai_analysis = ""
    citations: list[dict[str, Any]] = []

    analysis_file_ids = [postmortem_file_id]
    if runbook_file_id:
        analysis_file_ids.append(runbook_file_id)
    analysis_file_ids.extend(past_postmortem_ids)

    analysis_prompt = (
        "Analyze this incident postmortem and runbook. What are the code-level "
        "root causes? What specific permanent code fixes would prevent this "
        "incident from recurring? Be specific about which files and what kind "
        "of changes are needed."
    )

    try:
        ai_result = ai_ask_multi(
            file_ids=analysis_file_ids,
            prompt=analysis_prompt,
            include_citations=True,
        )
        ai_analysis = ai_result.get("answer", "")
        citations = ai_result.get("citations", [])
        print(f"[intake] Box AI analysis complete ({len(ai_analysis)} chars)")
    except Exception as exc:
        print(f"[intake] Box AI Ask failed, will rely on Bedrock fallback: {exc}")

    # ------------------------------------------------------------------
    # Step 4: Extract structured tasks
    # ------------------------------------------------------------------
    tasks: list[dict[str, Any]] = []

    # Try Box AI Extract Structured first
    try:
        extract_result = ai_extract_structured(
            file_id=postmortem_file_id,
            template_key="auto_fix_task",
            include_confidence=True,
            include_reference=True,
        )
        raw_tasks = extract_result.get("tasks", [])
        if isinstance(raw_tasks, list) and len(raw_tasks) > 0:
            tasks = raw_tasks
            print(f"[intake] Box AI extracted {len(tasks)} tasks")
        else:
            raise ValueError("No tasks returned from ai_extract_structured")
    except Exception as exc:
        print(f"[intake] Box AI extract failed ({exc}), falling back to Bedrock")
        try:
            tasks = _bedrock_extract_tasks(postmortem_text, ai_analysis, incident_id)
            print(f"[intake] Bedrock extracted {len(tasks)} tasks")
        except Exception as bedrock_exc:
            print(f"[intake] Bedrock extraction also failed: {bedrock_exc}")
            timeline_add(incident_id, "auto_fix", "Task extraction failed in both Box AI and Bedrock")
            return {
                "statusCode": 500,
                "body": "Failed to extract tasks from postmortem",
                "incident_id": incident_id,
            }

    # Filter by confidence threshold
    tasks = [
        t for t in tasks
        if float(t.get("confidence_score", 0)) >= CONFIDENCE_THRESHOLD
    ]
    print(f"[intake] {len(tasks)} tasks above confidence threshold {CONFIDENCE_THRESHOLD}")

    if not tasks:
        timeline_add(incident_id, "auto_fix", "No tasks above confidence threshold")
        return {
            "statusCode": 200,
            "incident_id": incident_id,
            "tasks_extracted": 0,
            "body": "No tasks met confidence threshold",
        }

    # ------------------------------------------------------------------
    # Step 5: Write tasks to Box + DynamoDB
    # ------------------------------------------------------------------
    tasks_folder_id = create_subfolder(box_folder_id, "tasks")
    now_iso = datetime.now(timezone.utc).isoformat(timespec="milliseconds") + "Z"

    for task in tasks:
        task_id = task["task_id"]
        priority = task.get("priority", "P2")
        task_type = task.get("type", "code_fix")
        confidence = float(task.get("confidence_score", 0))

        # Build task markdown
        task_md = (
            f"# {task_id}: {task.get('title', 'Untitled')}\n\n"
            f"**Incident:** {incident_id}\n"
            f"**Type:** {task_type}\n"
            f"**Priority:** {priority}\n"
            f"**Confidence:** {confidence}\n\n"
            f"## Description\n{task.get('description', '')}\n\n"
            f"## Files to Examine\n"
        )
        for f in task.get("files_to_examine", []):
            task_md += f"- {f}\n"
        task_md += (
            f"\n## Acceptance Criteria\n{task.get('acceptance_criteria', '')}\n\n"
            f"## Root Cause Link\n{task.get('root_cause_link', '')}\n"
        )

        # Upload task file to Box
        try:
            task_file_id = upload_text_file(tasks_folder_id, f"{task_id}.md", task_md)

            apply_metadata(task_file_id, "auto_fix_task", {
                "incident_id": incident_id,
                "task_id": task_id,
                "status": "extracted",
                "priority": priority,
                "task_type": task_type,
                "alarm_name": alarm_name,
                "confidence_score": confidence,
            })
            task["box_file_id"] = task_file_id
        except Exception as exc:
            print(f"[intake] Failed to upload/tag task {task_id} in Box: {exc}")

        # Write to DynamoDB
        try:
            tasks_table.put_item(Item={
                "incident_id": incident_id,
                "task_id": task_id,
                "title": task.get("title", ""),
                "type": task_type,
                "description": task.get("description", ""),
                "files_to_examine": task.get("files_to_examine", []),
                "acceptance_criteria": task.get("acceptance_criteria", ""),
                "priority": priority,
                "root_cause_link": task.get("root_cause_link", ""),
                "confidence_score": str(confidence),
                "status": "extracted",
                "alarm_name": alarm_name,
                "box_file_id": task.get("box_file_id", ""),
                "created_at": now_iso,
            })
        except Exception as exc:
            print(f"[intake] Failed to write task {task_id} to DynamoDB: {exc}")

    print(f"[intake] Wrote {len(tasks)} tasks to Box and DynamoDB")

    # ------------------------------------------------------------------
    # Step 6: Upload plan + invoke dispatcher
    # ------------------------------------------------------------------
    plan_md = _build_plan_markdown(incident_id, alarm_name, ai_analysis, citations, tasks)
    try:
        plan_file_id = upload_text_file(box_folder_id, "auto_fix_plan.md", plan_md)
        print(f"[intake] Uploaded auto_fix_plan.md ({plan_file_id})")
    except Exception as exc:
        print(f"[intake] Failed to upload auto_fix_plan.md: {exc}")

    timeline_add(
        incident_id,
        "auto_fix",
        f"Extracted {len(tasks)} tasks from postmortem",
    )

    # Invoke dispatcher asynchronously
    try:
        dispatcher_payload = {
            "incident_id": incident_id,
            "task_ids": [t["task_id"] for t in tasks],
        }
        lambda_client.invoke(
            FunctionName=DISPATCHER_FUNCTION_NAME,
            InvocationType="Event",
            Payload=json.dumps(dispatcher_payload),
        )
        print(f"[intake] Dispatched {len(tasks)} tasks to {DISPATCHER_FUNCTION_NAME}")
    except Exception as exc:
        print(f"[intake] Failed to invoke dispatcher: {exc}")
        timeline_add(incident_id, "auto_fix", f"Dispatcher invocation failed: {exc}")

    return {
        "statusCode": 200,
        "incident_id": incident_id,
        "tasks_extracted": len(tasks),
    }
