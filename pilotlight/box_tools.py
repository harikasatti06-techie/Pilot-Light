"""Box tools. STUBS until P3's real implementations land. Keep the signatures unchanged."""


def create_incident_folder(incident_id: str) -> str:
    return "stub-folder-" + incident_id


def find_runbook(alarm_name: str) -> str | None:
    return "stub-runbook-file"


def write_briefing(folder_id: str, incident_id: str, text: str) -> None:
    print(f"[stub] briefing.md for {incident_id} in {folder_id}: {text}")
