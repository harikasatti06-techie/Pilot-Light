"""Shared tool contract for Pilot Light.

Persons 1 and 3 replace the stub bodies with real implementations.
Person 2 (voice agent) calls these. Every function returns short, speakable text.
Keep the signatures unchanged.
"""


def query_logs(incident_id: str, minutes: int = 15) -> str:
    """Summarize recent error logs for the incident's service. (P1)"""
    return "In the last 15 minutes there were 212 five-hundred errors from checkout-api, mostly DynamoDB throttling and timeouts."


def what_changed(incident_id: str, minutes: int = 60) -> str:
    """Recent SSM parameter and CloudTrail changes. (P1)"""
    return "Forty minutes ago the SSM parameter checkout slash db-mode was changed from normal to broken."


def ask_runbook(incident_id: str, question: str) -> str:
    """Box AI Q&A over the incident's runbook. (P3)"""
    return "The runbook says to revert the db-mode parameter to normal, then watch the error rate for five minutes."


def get_briefing(incident_id: str) -> str:
    """Spoken opening briefing for the on-call engineer. (P3)"""
    return "Checkout API is returning high five-hundred errors. Severity is high. A recent config change is the likely cause."


def execute_remediation(incident_id: str, action: str, confirmed: bool) -> str:
    """Run an allowlisted SSM revert. Must refuse unless confirmed is True. (P1)"""
    if not confirmed:
        return "I need a verbal confirmation before I run that."
    return f"Done. I ran {action}. Errors should drop within a minute."


def log_to_incident(incident_id: str, event_type: str, text: str) -> None:
    """Write to the DynamoDB timeline and the Box incident folder.

    event_type is one of: alarm, call, tool, action, note.
    """
    print(f"[{incident_id}] {event_type}: {text}")


def page_teammate(incident_id: str, message: str) -> str:
    """Page a second responder. First on the cut list. (P1)"""
    return "I've paged a teammate."
