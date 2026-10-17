# Timeline

- Stored in CloudWatch Logs group `/pilotlight/timeline`, one log stream per `incident_id`
- Each event is JSON: `ts` (ISO-8601 UTC with milliseconds), `type`, `text`
- `type`: alarm | briefing | call | user | agent | tool | action | postmortem
- Write with `pilotlight.timeline.add(incident_id, type_, text)`, read with `pilotlight.timeline.list_all(incident_id)` (oldest first)
