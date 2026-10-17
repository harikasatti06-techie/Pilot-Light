"""Run the auto-fix pipeline.

Usage:
    python -m pilotlight.auto_fix [INCIDENT_ID]
"""
import os
import sys

from .. import box_tools, incidents, timeline
from ..box_client import client
from .extract import extract_tasks
from .implement import implement_task


def _find_file_in_folder(folder_id: str, name: str) -> str | None:
    """Find a file by name in a Box folder."""
    items = client().folders.get_folder_items(folder_id)
    for item in items.entries or []:
        if item.name == name:
            return item.id
    return None


def run(incident_id: str) -> list[str]:
    """Run the full auto-fix pipeline. Returns list of PR URLs."""
    print(f"\n{'='*60}")
    print(f"  PILOT LIGHT AUTO-FIX: {incident_id}")
    print(f"{'='*60}\n")

    # 1. Load incident record
    rec = incidents.get(incident_id)
    if not rec:
        print(f"[auto_fix] Incident {incident_id} not found")
        return []

    folder_id = rec.get("box_folder_id", "")
    alarm_name = rec.get("alarm_name", "pilotlight-checkout-5xx")
    runbook_id = rec.get("runbook_file_id", "")

    if not folder_id:
        print("[auto_fix] No Box folder for this incident")
        return []

    # 2. Find postmortem and transcript in Box folder
    postmortem_id = _find_file_in_folder(folder_id, "postmortem.md")
    transcript_id = _find_file_in_folder(folder_id, "transcript.md")

    if not postmortem_id:
        print("[auto_fix] No postmortem.md in the incident folder")
        return []

    timeline.add(incident_id, "autofix", "Auto-fix pipeline started")

    # 3. Extract tasks
    tasks, analysis = extract_tasks(
        incident_id=incident_id,
        postmortem_file_id=postmortem_id,
        transcript_file_id=transcript_id,
        runbook_file_id=runbook_id if runbook_id and not runbook_id.startswith("stub") else None,
        alarm_name=alarm_name,
    )

    if not tasks:
        print("[auto_fix] No tasks extracted")
        timeline.add(incident_id, "autofix", "No actionable tasks found in postmortem")
        return []

    # 4. Upload task plan to Box
    plan_md = f"# Auto-Fix Plan: {incident_id}\n\n"
    plan_md += f"**Analysis:** {analysis.get('answer', 'N/A')[:500]}\n\n"
    plan_md += f"**Tasks extracted:** {len(tasks)}\n\n"
    for t in tasks:
        plan_md += f"## {t['task_id']}: {t['title']}\n"
        plan_md += f"- Type: {t.get('type', '?')}\n"
        plan_md += f"- Priority: {t.get('priority', '?')}\n"
        plan_md += f"- Description: {t.get('description', '?')}\n\n"
    box_tools.upload_text(folder_id, "auto_fix_plan.md", plan_md)
    print(f"[auto_fix] Plan uploaded to Box")

    # 5. Implement each task
    repo_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    pr_urls = []

    for task in tasks:
        task["alarm_name"] = alarm_name
        pr_url = implement_task(
            incident_id=incident_id,
            task=task,
            repo_path=repo_path,
            box_folder_id=folder_id,
            past_fixes_context=analysis.get("answer", ""),
        )
        if pr_url:
            pr_urls.append(pr_url)

    # 6. Upload summary to Box
    summary = f"# Auto-Fix Summary: {incident_id}\n\n"
    summary += f"- Tasks extracted: {len(tasks)}\n"
    summary += f"- PRs created: {len(pr_urls)}\n"
    summary += f"- Failed: {len(tasks) - len(pr_urls)}\n\n"
    if pr_urls:
        summary += "## Pull Requests\n\n"
        for url in pr_urls:
            summary += f"- {url}\n"
    summary_id = box_tools.upload_text(folder_id, "pr_summary.md", summary)

    # 7. Create review task on summary
    try:
        box_tools.create_review_task(summary_id, f"Review auto-fix PRs for {incident_id}")
        print("[auto_fix] Review task created in Box")
    except Exception as e:
        print(f"[auto_fix] Review task creation failed: {e}")

    timeline.add(
        incident_id, "autofix",
        f"Auto-fix complete: {len(pr_urls)} PRs created from {len(tasks)} tasks"
    )

    print(f"\n{'='*60}")
    print(f"  AUTO-FIX COMPLETE: {len(pr_urls)}/{len(tasks)} PRs created")
    for url in pr_urls:
        print(f"  {url}")
    print(f"{'='*60}\n")

    return pr_urls


def main():
    if len(sys.argv) > 1:
        iid = sys.argv[1]
    else:
        rec = incidents.latest()
        if not rec:
            sys.exit("No incidents found. Pass an incident ID or run after an incident.")
        iid = rec["incident_id"]
        print(f"[auto_fix] Using latest incident: {iid}")

    urls = run(iid)
    if not urls:
        sys.exit(1)


if __name__ == "__main__":
    main()
