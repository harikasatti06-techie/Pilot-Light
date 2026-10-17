"""Box SDK helper functions using box-sdk-gen with CCG auth."""

from __future__ import annotations

import io
import logging
from typing import Any

from box_sdk_gen import (
    BoxCCGAuth,
    BoxClient,
    CCGConfig,
)
from box_sdk_gen.schemas import (
    AiItemBase,
    AiItemBaseTypeField,
    AiResponseFull,
    CreateAiAskItems,
    CreateAiAskMode,
    CreateAiTextGenItems,
    MetadataFull,
)
from box_sdk_gen.managers.uploads import UploadFileAttributes, UploadFileAttributesParentField
from box_sdk_gen.box.errors import BoxAPIError

from pilotlight.config import (
    BOX_CLIENT_ID,
    BOX_CLIENT_SECRET,
    BOX_ENTERPRISE_ID,
)

logger = logging.getLogger(__name__)

_client: BoxClient | None = None


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def get_client() -> BoxClient:
    """Singleton CCG-authenticated Box client."""
    global _client
    if _client is None:
        cfg = CCGConfig(
            client_id=BOX_CLIENT_ID,
            client_secret=BOX_CLIENT_SECRET,
            enterprise_id=BOX_ENTERPRISE_ID,
        )
        auth = BoxCCGAuth(config=cfg)
        _client = BoxClient(auth=auth)
    return _client


# ---------------------------------------------------------------------------
# File operations
# ---------------------------------------------------------------------------

def download_file_content(file_id: str) -> str:
    """Download a file's content as a text string."""
    client = get_client()
    stream = client.downloads.download_file(file_id=file_id)
    content = stream.read()
    if isinstance(content, bytes):
        return content.decode("utf-8")
    return content


def upload_text_file(folder_id: str, name: str, content: str) -> str:
    """Upload a text file to a folder. Returns file_id.

    If a file with the same name already exists, uploads a new version instead.
    """
    client = get_client()
    data = content.encode("utf-8")
    stream = io.BytesIO(data)

    try:
        attributes = UploadFileAttributes(
            name=name,
            parent=UploadFileAttributesParentField(id=folder_id),
        )
        files = client.uploads.upload_file(
            attributes=attributes,
            file=stream,
            file_file_name=name,
        )
        return files.entries[0].id
    except BoxAPIError as exc:
        # 409 means a file with the same name already exists -- upload new version
        if exc.response_info.status_code == 409:
            existing_id = exc.response_info.body.get("context_info", {}).get(
                "conflicts", {}
            ).get("id")
            if not existing_id:
                raise
            stream.seek(0)
            files = client.uploads.upload_file_version(
                file_id=existing_id,
                attributes=UploadFileAttributes(name=name),
                file=stream,
                file_file_name=name,
            )
            return files.entries[0].id
        raise


# ---------------------------------------------------------------------------
# Folder operations
# ---------------------------------------------------------------------------

def create_subfolder(parent_folder_id: str, name: str) -> str:
    """Create a subfolder. If it already exists, return existing folder_id."""
    client = get_client()
    try:
        folder = client.folders.create_folder(name=name, parent_id=parent_folder_id)
        return folder.id
    except BoxAPIError as exc:
        if exc.response_info.status_code == 409:
            # Folder already exists -- extract its id from the conflict info
            existing_id = exc.response_info.body.get("context_info", {}).get(
                "conflicts", [{}]
            )[0].get("id")
            if existing_id:
                return existing_id
        raise


# ---------------------------------------------------------------------------
# Metadata operations
# ---------------------------------------------------------------------------

def apply_metadata(file_id: str, template_key: str, metadata: dict) -> None:
    """Apply a metadata template to a file.

    Scope is enterprise_{BOX_ENTERPRISE_ID}.
    """
    client = get_client()
    scope = f"enterprise_{BOX_ENTERPRISE_ID}"
    client.file_metadata.create_file_metadata_by_id(
        file_id=file_id,
        scope=scope,
        template_key=template_key,
        request_body=metadata,
    )


def update_metadata(file_id: str, template_key: str, updates: list[dict]) -> None:
    """Update metadata on a file using JSON Patch operations.

    *updates* is a list of dicts, e.g.::

        [{"op": "replace", "path": "/status", "value": "pr_created"}]
    """
    client = get_client()
    scope = f"enterprise_{BOX_ENTERPRISE_ID}"
    client.file_metadata.update_file_metadata_by_id(
        file_id=file_id,
        scope=scope,
        template_key=template_key,
        request_body=updates,
    )


def query_metadata(
    template_key: str,
    ancestor_folder_id: str,
    query: str | None = None,
    params: dict | None = None,
) -> list:
    """Execute a metadata query. Returns list of file/folder items.

    The ``from`` field is ``enterprise_{BOX_ENTERPRISE_ID}.{template_key}``.
    """
    client = get_client()
    from_template = f"enterprise_{BOX_ENTERPRISE_ID}.{template_key}"
    result = client.search.search_by_metadata_query(
        from_=from_template,
        ancestor_folder_id=ancestor_folder_id,
        query=query,
        query_params=params or {},
    )
    return result.entries


# ---------------------------------------------------------------------------
# Box AI helpers
# ---------------------------------------------------------------------------

def ai_ask_multi(
    file_ids: list[str],
    prompt: str,
    include_citations: bool = True,
) -> dict:
    """Box AI Ask in multiple_item_qa mode.

    Returns ``{"answer": str, "citations": list}``.
    """
    client = get_client()
    items = [
        AiItemBase(id=fid, type=AiItemBaseTypeField.FILE)
        for fid in file_ids
    ]
    response: AiResponseFull = client.ai.create_ai_ask(
        mode=CreateAiAskMode.MULTIPLE_ITEM_QA,
        prompt=prompt,
        items=items,
    )
    result: dict[str, Any] = {"answer": response.answer}
    if include_citations and hasattr(response, "citations"):
        result["citations"] = response.citations
    else:
        result["citations"] = []
    return result


def ai_extract_structured(
    file_id: str,
    template_key: str,
    include_confidence: bool = True,
    include_reference: bool = True,
) -> dict:
    """Box AI Extract Structured using a metadata template.

    Returns the full response dict.
    """
    client = get_client()
    scope = f"enterprise_{BOX_ENTERPRISE_ID}"
    items = [AiItemBase(id=file_id, type=AiItemBaseTypeField.FILE)]
    response = client.ai.create_ai_extract_structured(
        items=items,
        metadata_template={
            "template_key": template_key,
            "scope": scope,
        },
    )
    return response.to_dict() if hasattr(response, "to_dict") else vars(response)


def ai_text_gen(file_id: str, prompt: str) -> str:
    """Box AI Text Gen grounded on a single file. Returns generated text."""
    client = get_client()
    items = [
        CreateAiTextGenItems(id=file_id, type=AiItemBaseTypeField.FILE)
    ]
    response = client.ai.create_ai_text_gen(
        prompt=prompt,
        items=items,
    )
    return response.answer


# ---------------------------------------------------------------------------
# Collaboration & tasks
# ---------------------------------------------------------------------------

def create_review_task(file_id: str, message: str, reviewer_login: str) -> None:
    """Create a review task on a file and assign it to the reviewer."""
    client = get_client()
    task = client.tasks.create_task(
        item={"type": "file", "id": file_id},
        message=message,
        action="review",
    )
    client.tasks.create_task_assignment(
        task_id=task.id,
        assign_to={"login": reviewer_login},
    )


def add_collaboration(folder_id: str, login: str, role: str = "editor") -> None:
    """Add a user as collaborator on a folder."""
    client = get_client()
    try:
        client.user_collaborations.create_collaboration(
            item={"type": "folder", "id": folder_id},
            accessible_by={"type": "user", "login": login},
            role=role,
        )
    except BoxAPIError as exc:
        # 409 means the collaboration already exists -- safe to ignore
        if exc.response_info.status_code == 409:
            logger.info(
                "Collaboration already exists for %s on folder %s", login, folder_id
            )
        else:
            raise
