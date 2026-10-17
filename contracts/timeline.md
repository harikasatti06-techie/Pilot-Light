# Timeline table

- DynamoDB table: `pilotlight-timeline`
- Partition key: `incident_id` (S)
- Sort key: `ts` (S, ISO-8601 UTC with milliseconds)
- Fields: `type` (alarm | briefing | call | user | agent | tool | action | postmortem), `text`
- `log_to_incident` writes here. The dashboard reads from here.
