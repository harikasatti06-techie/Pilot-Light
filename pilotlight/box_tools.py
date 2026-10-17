"""Box tools: incident folders, runbook lookup by metadata, uploads, review tasks, runbook Q&A.
Keep the signatures unchanged; the incident handler, postmortem, and voice agent call these."""
import datetime
import io

import boto3
from box_sdk_gen.box.errors import BoxAPIError
from box_sdk_gen.managers.ai import CreateAiAskMode
from box_sdk_gen.managers.folders import CreateFolderParent
from box_sdk_gen.managers.task_assignments import CreateTaskAssignmentAssignTo, CreateTaskAssignmentTask
from box_sdk_gen.managers.tasks import CreateTaskAction, CreateTaskItem, CreateTaskItemTypeField
from box_sdk_gen.managers.uploads import (UploadFileAttributes, UploadFileAttributesParentField,
                                          UploadFileVersionAttributes)
from box_sdk_gen.managers.user_collaborations import (CreateCollaborationAccessibleBy,
                                                      CreateCollaborationAccessibleByTypeField,
                                                      CreateCollaborationItem,
                                                      CreateCollaborationItemTypeField,
                                                      CreateCollaborationRole)
from box_sdk_gen.schemas.ai_item_ask import AiItemAsk, AiItemAskTypeField

from . import incidents, timeline
from .box_client import client
from .config import (AWS_REGION, BOX_ENTERPRISE_ID, BOX_INCIDENTS_FOLDER_ID, BOX_REVIEWER_LOGIN,
                     BOX_RUNBOOKS_FOLDER_ID, TEXT_MODEL_ID)

QA_PROMPT = "Answer in 2 short spoken sentences: {question}"
_file_folder: dict[str, str] = {}  # file_id -> folder_id, for the review task fallback


def _status(e: BoxAPIError) -> int | None:
    return getattr(e.response_info, "status_code", None)


def _conflict_id(e: BoxAPIError) -> str | None:
    conflicts = (getattr(e.response_info, "context_info", None) or {}).get("conflicts")
    if isinstance(conflicts, list):
        conflicts = conflicts[0] if conflicts else None
    return conflicts.get("id") if isinstance(conflicts, dict) else None


def create_incident_folder(incident_id: str) -> str:
    try:
        folder_id = client().folders.create_folder(incident_id, CreateFolderParent(id=BOX_INCIDENTS_FOLDER_ID)).id
    except BoxAPIError as e:
        folder_id = _conflict_id(e) if _status(e) == 409 else None
        if not folder_id:
            raise
    timeline.add(incident_id, "tool", f"box: incident folder {incident_id} ready (id {folder_id})")
    return folder_id


def find_runbook(alarm_name: str) -> str | None:
    try:
        r = client().search.search_by_metadata_query(
            f"enterprise_{BOX_ENTERPRISE_ID}.runbook", BOX_RUNBOOKS_FOLDER_ID,
            query="alarm_name = :a", query_params={"a": alarm_name}, limit=1)
        if r.entries:
            return r.entries[0].id
        return None
    except BoxAPIError as e:
        print(f"[box] metadata query failed ({_status(e)}), falling back to folder listing")
    for item in client().folders.get_folder_items(BOX_RUNBOOKS_FOLDER_ID).entries or []:
        if item.type == "file" and item.name.endswith(".md") and "checkout" in item.name:
            return item.id
    return None


def write_briefing(folder_id: str, incident_id: str, text: str) -> None:
    upload_text(folder_id, "briefing.md", f"# Briefing: {incident_id}\n\n{text}\n")
    timeline.add(incident_id, "tool", "box: briefing.md written to the incident folder")


def upload_text(folder_id: str, name: str, text: str) -> str:
    data = text.encode()
    try:
        f = client().uploads.upload_file(
            UploadFileAttributes(name=name, parent=UploadFileAttributesParentField(id=folder_id)),
            io.BytesIO(data))
        file_id = f.entries[0].id
    except BoxAPIError as e:
        existing = _conflict_id(e) if _status(e) == 409 else None
        if not existing:
            raise
        f = client().uploads.upload_file_version(existing, UploadFileVersionAttributes(name=name), io.BytesIO(data))
        file_id = f.entries[0].id
    _file_folder[file_id] = folder_id
    return file_id


def _collaborate(folder_id: str, login: str) -> None:
    try:
        client().user_collaborations.create_collaboration(
            CreateCollaborationItem(type=CreateCollaborationItemTypeField.FOLDER, id=folder_id),
            CreateCollaborationAccessibleBy(type=CreateCollaborationAccessibleByTypeField.USER, login=login),
            CreateCollaborationRole.EDITOR)
    except BoxAPIError as e:
        if _status(e) != 409:  # 409 means already a collaborator
            raise


def create_review_task(file_id: str, message: str) -> None:
    due = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)
    task = client().tasks.create_task(
        CreateTaskItem(id=file_id, type=CreateTaskItemTypeField.FILE),
        action=CreateTaskAction.REVIEW, message=message, due_at=due)
    if not BOX_REVIEWER_LOGIN:
        print("[box] review task created, BOX_REVIEWER_LOGIN not set, left unassigned")
        return

    def assign():
        client().task_assignments.create_task_assignment(
            CreateTaskAssignmentTask(id=task.id), CreateTaskAssignmentAssignTo(login=BOX_REVIEWER_LOGIN))

    try:
        assign()
    except BoxAPIError as e:
        folder_id = _file_folder.get(file_id) or BOX_INCIDENTS_FOLDER_ID
        print(f"[box] task assignment failed ({_status(e)}), collaborating reviewer on folder {folder_id} and retrying")
        _collaborate(folder_id, BOX_REVIEWER_LOGIN)
        assign()


def read_runbook_text(file_id: str) -> str:
    stream = client().downloads.download_file(file_id)
    return stream.read().decode("utf-8", errors="replace") if stream else ""


def _ask_bedrock(runbook: str, question: str) -> str:
    br = boto3.client("bedrock-runtime", region_name=AWS_REGION)
    r = br.converse(
        modelId=TEXT_MODEL_ID or "us.amazon.nova-2-lite-v1:0",
        system=[{"text": "You answer questions using only the runbook provided. Plain spoken sentences, no markdown."}],
        messages=[{"role": "user", "content": [{"text": f"RUNBOOK:\n{runbook}\n\n{QA_PROMPT.format(question=question)}"}]}],
        inferenceConfig={"maxTokens": 200, "temperature": 0.2})
    return r["output"]["message"]["content"][0]["text"].strip()


def ask_runbook(incident_id: str, question: str) -> str:
    rec = incidents.get(incident_id) or {}
    file_id = rec.get("runbook_file_id") or find_runbook(rec.get("alarm_name") or "pilotlight-checkout-5xx")
    if not file_id or file_id.startswith("stub"):
        text = "I could not find a runbook for this alarm."
        timeline.add(incident_id, "tool", f"ask_runbook: {text}")
        return text
    try:
        r = client().ai.create_ai_ask(CreateAiAskMode.SINGLE_ITEM_QA, QA_PROMPT.format(question=question),
                                      [AiItemAsk(id=file_id, type=AiItemAskTypeField.FILE)])
        text, path = r.answer.strip(), "box_ai"
    except Exception as e:
        print(f"[box] Box AI unavailable ({type(e).__name__}), answering with Bedrock over the runbook")
        text, path = _ask_bedrock(read_runbook_text(file_id), question), "bedrock"
    text = " ".join(text.replace("*", "").replace("#", "").replace("`", "").split())
    timeline.add(incident_id, "tool", f"ask_runbook ({path}): {text}")
    return text
