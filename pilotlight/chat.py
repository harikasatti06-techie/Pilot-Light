"""Terminal chat with the incident agent, for testing without a phone.

Run: python -m pilotlight.chat [INCIDENT_ID]   (defaults to the latest incident)
Type bye or exit to hang up.
"""
import sys

from . import incidents
from .agent import IncidentAgent


def main() -> None:
    rec = incidents.get(sys.argv[1]) if len(sys.argv) > 1 else incidents.latest()
    if not rec:
        sys.exit("No incident found. Run scripts/break.sh with scripts/start.sh running first.")
    iid = rec["incident_id"]
    agent = IncidentAgent(iid)
    print(f"[{iid}] call connected\n")
    print(f"Pilot Light: {agent.opening()}\n")
    while True:
        try:
            text = input("You: ").strip()
        except EOFError:
            break
        if text.lower() in ("bye", "exit", "quit"):
            break
        if text:
            print(f"Pilot Light: {agent.respond(text)}\n")

    transcript = "\n".join(agent.transcript)
    try:
        from . import postmortem
        generate = getattr(postmortem, "generate", None)
    except ImportError:
        generate = None
    if generate:
        try:
            generate(iid, rec.get("box_folder_id", ""), transcript)
            print("\nPostmortem generated.")
        except Exception as e:
            print(f"\nPostmortem failed: {e}\n\n{transcript}")
    else:
        print(f"\n--- transcript ---\n{transcript}")


if __name__ == "__main__":
    main()
