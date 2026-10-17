"""System prompt for the voice agent. Reuses the text agent's rules and adds the briefing."""
from pilotlight import incidents
from pilotlight.agent import SYSTEM_PROMPT

KICKOFF = "The call just connected. Give the briefing now."


def build(incident_id: str) -> str:
    rec = incidents.get(incident_id) or {}
    briefing = rec.get("briefing_text") or "No briefing recorded. Use the get_briefing tool."
    return (SYSTEM_PROMPT.format(incident_id=incident_id)
            + f"\n\nBriefing: {briefing}"
            + "\n- This is a live phone call. Keep every turn under 30 words.")
