"""Box tools. STUBS until P3's (Neha) real implementations land. Keep the signatures unchanged."""
from pathlib import Path

from .config import STATE_DIR

OUTBOX = Path(STATE_DIR) / "box_outbox"
_file_folders: dict[str, str] = {}


def create_incident_folder(incident_id: str) -> str:
    return "stub-folder-" + incident_id


def find_runbook(alarm_name: str) -> str | None:
    return "stub-runbook-file"


def write_briefing(folder_id: str, incident_id: str, text: str) -> None:
    print(f"[stub] briefing.md for {incident_id} in {folder_id}: {text}")


def upload_text(folder_id: str, name: str, text: str) -> str:
    """STUB: writes a local copy to .state/box_outbox/<folder_id>/<name>."""
    d = OUTBOX / folder_id
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(text)
    file_id = f"stub-file-{name}"
    _file_folders[file_id] = folder_id
    return file_id


def create_review_task(file_id: str, message: str) -> None:
    """STUB: appends the task to .state/box_outbox/<folder_id>/tasks.txt."""
    folder_id = _file_folders.get(file_id)
    if folder_id is None:
        print(f"[stub] review task on {file_id}: {message}")
        return
    with open(OUTBOX / folder_id / "tasks.txt", "a") as f:
        f.write(f"{file_id}\t{message}\n")
