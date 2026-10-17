"""Idempotent Box setup: verify auth and folders, upload the runbook with its metadata,
and list (optionally add) collaborators so the team can see the folders in the web UI.

Run: python scripts/box_setup.py [--collab a@x.com,b@y.com]
"""
import argparse
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from box_sdk_gen.box.errors import BoxAPIError  # noqa: E402
from box_sdk_gen.managers.file_metadata import CreateFileMetadataByIdScope  # noqa: E402
from box_sdk_gen.managers.metadata_templates import GetMetadataTemplateScope  # noqa: E402
from box_sdk_gen.managers.uploads import UploadFileAttributes, UploadFileAttributesParentField  # noqa: E402

from pilotlight.box_client import client  # noqa: E402
from pilotlight.box_tools import _collaborate  # noqa: E402
from pilotlight.config import BOX_INCIDENTS_FOLDER_ID, BOX_RUNBOOKS_FOLDER_ID  # noqa: E402

RUNBOOK = ROOT / "runbooks" / "checkout-5xx.md"
METADATA = {"service": "checkout-api", "alarm_name": "pilotlight-checkout-5xx", "severity": "sev2"}


def severity_key(wanted: str) -> str:
    """The severity field is an enum; match the option key the template actually uses."""
    t = client().metadata_templates.get_metadata_template(GetMetadataTemplateScope.ENTERPRISE, "runbook")
    for f in t.fields or []:
        if f.key == "severity" and f.options:
            for o in f.options:
                if o.key.lower() == wanted.lower():
                    return o.key
            print(f"  severity options: {[o.key for o in f.options]}")
    return wanted


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--collab", default="", help="comma-separated Box logins to add as editors")
    args = ap.parse_args()
    c = client()

    me = c.users.get_user_me()
    print(f"auth:      OK as service account '{me.name}'")
    for label, fid in [("Runbooks", BOX_RUNBOOKS_FOLDER_ID), ("Incidents", BOX_INCIDENTS_FOLDER_ID)]:
        f = c.folders.get_folder_by_id(fid)
        print(f"{label + ':':<10} OK '{f.name}' (id {fid})")

    items = c.folders.get_folder_items(BOX_RUNBOOKS_FOLDER_ID).entries or []
    existing = next((i for i in items if i.type == "file" and i.name == RUNBOOK.name), None)
    if existing:
        file_id = existing.id
        print(f"runbook:   exists {RUNBOOK.name} (id {file_id})")
    else:
        up = c.uploads.upload_file(
            UploadFileAttributes(name=RUNBOOK.name, parent=UploadFileAttributesParentField(id=BOX_RUNBOOKS_FOLDER_ID)),
            io.BytesIO(RUNBOOK.read_bytes()))
        file_id = up.entries[0].id
        print(f"runbook:   uploaded {RUNBOOK.name} (id {file_id})")
    others = [i.name for i in items if i.name != RUNBOOK.name]
    if others:
        print(f"           other items in Runbooks: {others}")

    md = dict(METADATA, severity=severity_key(METADATA["severity"]))
    try:
        c.file_metadata.create_file_metadata_by_id(file_id, CreateFileMetadataByIdScope.ENTERPRISE, "runbook", md)
        print(f"metadata:  applied {md}")
    except BoxAPIError as e:
        if e.response_info.status_code != 409:
            raise
        current = c.file_metadata.get_file_metadata_by_id(file_id, "enterprise", "runbook")
        cur = {k: (current.extra_data or {}).get(k) for k in md}
        if cur != md:
            print(f"metadata:  present but differs {cur}; expected {md}. Fix in the Box UI or remove and rerun.")
        else:
            print(f"metadata:  already applied {md}")

    for login in [x.strip() for x in args.collab.split(",") if x.strip()]:
        for fid in (BOX_RUNBOOKS_FOLDER_ID, BOX_INCIDENTS_FOLDER_ID):
            _collaborate(fid, login)
        print(f"collab:    {login} is an editor on Runbooks and Incidents")

    for label, fid in [("Runbooks", BOX_RUNBOOKS_FOLDER_ID), ("Incidents", BOX_INCIDENTS_FOLDER_ID)]:
        collabs = c.list_collaborations.get_folder_collaborations(fid).entries or []
        names = [f"{getattr(x.accessible_by, 'login', None) or getattr(x.accessible_by, 'name', '?')} ({getattr(x.role, "value", x.role)})"
                 for x in collabs]
        owner = c.folders.get_folder_by_id(fid).owned_by
        print(f"{label} owner: {getattr(owner, 'login', '?')}; collaborators: {names or 'none'}")
    print("done")


if __name__ == "__main__":
    main()
