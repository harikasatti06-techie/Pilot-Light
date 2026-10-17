"""Dispatcher Lambda -- starts one CodeBuild build per extracted task."""

from __future__ import annotations

import json
import logging
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key, Attr

from pilotlight.config import (
    CODEBUILD_PROJECT,
    GITHUB_REPO,
    INCIDENTS_TABLE,
    TASKS_TABLE,
)
from pilotlight.timeline import add as timeline_add

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

codebuild = boto3.client("codebuild")
dynamodb = boto3.resource("dynamodb")
tasks_table = dynamodb.Table(TASKS_TABLE)
incidents_table = dynamodb.Table(INCIDENTS_TABLE)


def _env_var(name: str, value: str) -> dict[str, str]:
    """Build a CodeBuild environment-variable override dict."""
    return {"name": name, "value": value, "type": "PLAINTEXT"}


def _query_extracted_tasks(incident_id: str) -> list[dict[str, Any]]:
    """Return all tasks for *incident_id* whose status is 'extracted'."""
    response = tasks_table.query(
        KeyConditionExpression=Key("incident_id").eq(incident_id),
        FilterExpression=Attr("status").eq("extracted"),
    )
    return response.get("Items", [])


def _get_incident(incident_id: str) -> dict[str, Any]:
    """Fetch the incident record from DynamoDB."""
    response = incidents_table.get_item(Key={"incident_id": incident_id})
    item = response.get("Item")
    if not item:
        raise ValueError(f"Incident {incident_id} not found in {INCIDENTS_TABLE}")
    return item


def _start_build(
    incident_id: str,
    task: dict[str, Any],
    incident: dict[str, Any],
) -> str:
    """Start a CodeBuild build for a single task and return the build ID."""
    task_id = task["task_id"]
    task_json = json.dumps(task, default=str)

    env_overrides = [
        _env_var("INCIDENT_ID", incident_id),
        _env_var("TASK_ID", task_id),
        _env_var("TASK_JSON", task_json),
        _env_var("REPO_URL", GITHUB_REPO),
        _env_var("BOX_FOLDER_ID", incident.get("box_folder_id", "")),
        _env_var("BOX_INCIDENTS_FOLDER_ID", incident.get("box_incidents_folder_id", "")),
    ]

    response = codebuild.start_build(
        projectName=CODEBUILD_PROJECT,
        environmentVariablesOverride=env_overrides,
    )
    return response["build"]["id"]


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point -- dispatches one CodeBuild build per task.

    Parameters
    ----------
    event : dict
        Must contain ``incident_id``.
    context : Any
        Lambda context (unused).

    Returns
    -------
    dict
        ``{"builds_started": N, "build_ids": [...]}``
    """
    incident_id: str = event["incident_id"]
    logger.info("Dispatching tasks for incident %s", incident_id)

    tasks = _query_extracted_tasks(incident_id)
    if not tasks:
        logger.warning("No extracted tasks found for incident %s", incident_id)
        return {"builds_started": 0, "build_ids": []}

    incident = _get_incident(incident_id)
    build_ids: list[str] = []

    for task in tasks:
        task_id = task["task_id"]
        try:
            build_id = _start_build(incident_id, task, incident)
            build_ids.append(build_id)

            tasks_table.update_item(
                Key={"incident_id": incident_id, "task_id": task_id},
                UpdateExpression="SET #s = :s, build_id = :b",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":s": "dispatched", ":b": build_id},
            )

            timeline_add(
                incident_id,
                "auto-fix",
                f"Dispatched CodeBuild for TASK-{task_id} (build {build_id})",
            )
            logger.info("Started build %s for TASK-%s", build_id, task_id)

        except Exception:
            logger.exception("Failed to dispatch TASK-%s", task_id)
            timeline_add(
                incident_id,
                "auto-fix",
                f"Failed to dispatch CodeBuild for TASK-{task_id}",
            )

    logger.info(
        "Dispatched %d/%d builds for incident %s",
        len(build_ids),
        len(tasks),
        incident_id,
    )
    return {"builds_started": len(build_ids), "build_ids": build_ids}
