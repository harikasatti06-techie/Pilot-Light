# Timeline table

- DynamoDB table: `pilotlight-timeline`
- Partition key: `incident_id` (S)
- Sort key: `ts` (S, ISO-8601 UTC)
- Fields: `type` (alarm | call | tool | action | note), `text`
- `log_to_incident` writes here and to Box. The dashboard reads from here.
