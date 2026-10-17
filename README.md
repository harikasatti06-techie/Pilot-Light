# Pilot Light

Always on. Ignites when production breaks.

Box + AWS Agentic Enterprise AI Hackathon, Seattle, Oct 16 to 17.

When production breaks, Pilot Light phones the on-call engineer. A voice agent briefs them, answers questions, and runs approved remediation only after verbal confirmation. Every step is recorded in a Box incident folder, and a postmortem is drafted for review.

Flow: demo service breaks → CloudWatch alarm → EventBridge → Incident Lambda → Box incident folder → phone call → "confirm" → SSM remediation → transcript and postmortem in Box

## Layout

- `pilotlight/tools.py`: shared tool contract (stubs until real versions land)
- `contracts/`: incident object and timeline table
- `.env.example`: copy to `.env`, never commit secrets

## Rules

- Stubs first. One branch per person (`p1-zain`, `p2-voice`, `p3-box`, `p4-infra`). Small commits to main.
- Cut order if behind: `page_teammate`, hosted voice runtime, dashboard polish.
- Never cut: the phone call and the Box record.

## Services used

AWS: CloudWatch, EventBridge, Lambda, API Gateway, DynamoDB, SSM, CloudTrail, Bedrock (Nova 2 Sonic), CDK.
Box: Box API, Metadata templates, Box AI, Tasks.
