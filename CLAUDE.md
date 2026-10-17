# Pilot Light: Claude Code context

Read this before doing anything in this repo. It records what is already built, what is decided, and what is next, so no session repeats finished work. **Update the Build status section after every completed step and commit it with the work.**

## 1. Project in one paragraph

Hackathon project for the Box + AWS Agentic Enterprise AI Hackathon (Seattle, Oct 16 to 17, 2026). **Submission deadline Sat Oct 17, 1:00pm.** When production breaks, Pilot Light phones the on-call engineer. A voice agent (Amazon Nova 2 Sonic) briefs them, answers questions with live AWS data and Box runbooks, and runs an allowlisted fix only after the engineer says "confirm." Everything is recorded in a Box incident folder, and a postmortem is drafted and assigned as a Box review task.

Full plan and contracts: `~/Desktop/PILOT_LIGHT_BUILD_PLAN.md` (local to Zain's machine, not in the repo). Background and decisions: `~/Desktop/CLAUDE.md`. The repo code is the source of truth where they differ.

## 2. Team and working model

| Person | Role |
|---|---|
| P1 Zain | Runs this Claude Code session, deploys, integration lead, presents the pitch |
| P2 | Voice and telephony: accounts, credentials, phone testing |
| P3 | Box: app, metadata template, credentials, Box UI checks, deck, backup video |

**One builder.** All code is written in this one Claude Code session on Zain's laptop, in this one repo. P2 and P3 do console setup, send credentials, and test. Do not split work across sessions.

## 3. Build status

Last updated: Fri Oct 16, 2026.

### Done
- [x] Tooling on Zain's Mac: AWS CLI 2.38.1, Python 3.12.15 (Homebrew), AWS CDK 2.1145, `.venv` with `requirements.txt` installed
- [x] Repo scaffold, `.env.example`, `requirements.txt`, `contracts/`
- [x] `pilotlight/config.py`: env loading, `python-dotenv` optional so it imports inside Lambda
- [x] `pilotlight/timeline.py`: `add`, `list_all` (paginated)
- [x] `pilotlight/aws_tools.py`: real `query_logs`, `what_changed`, `execute_remediation` with `ALLOWED_ACTIONS`
- [x] `pilotlight/tools.py`: P1 tools wired to `aws_tools`, `log_to_incident` writes to the timeline, `get_briefing` reads `briefing_text` from the incident record. `ask_runbook`, `page_teammate` are still stubs.
- [x] `pilotlight/box_tools.py`: **stubs** for `create_incident_folder`, `find_runbook`, `write_briefing`
- [x] `services/checkout/handler.py`: fails with PaymentTimeout while `fail_mode` is `on`, emits a 1-second-resolution metric
- [x] `services/incident/handler.py`: alarm → what_changed + query_logs → briefing → incident record + timeline → Connect outbound call (`contact_id` saved on the incident). Skips the call while `CONNECT_*` is unset. Dedupes: no new incident while one for the same alarm is open and under 30 minutes old.
- [x] `infra/` CDK stack `PilotLight`: SSM param, both tables, checkout Lambda + HTTP API, 10s alarm, `PilotLight` dashboard, Incident Lambda with scoped IAM, EventBridge rule. `cdk synth` passes.
- [x] `scripts/`: `traffic.sh`, `break.sh`, `fix.sh`, `force_alarm.sh`, `status.sh`
- [x] Pushed to `main` (commit `b184c93`)
- [x] Branch `feature/connect-nova-sonic`: Amazon Connect + Nova Sonic voice path (see `connect/SETUP.md`)
  - `pilotlight/connect.py`: `start_call`, AI agent session lookup, `set_session_data`, `transcript`, `caller_confirmed`
  - `pilotlight/incidents.py`: incident record helpers (`get`, `put`, `update`, `latest_open`, `by_contact`)
  - `services/tools/`: AgentCore Gateway Lambda target. Dispatches five tools, enforces the code-level confirm check against the live transcript (fails closed)
  - `services/session/`: flow Lambda, puts `incident_id` and `briefing` into the AI agent session (`{{$.Custom.*}}`)
  - `services/hangup/`: on contact DISCONNECTED, transcript to timeline as `user`/`agent` rows, incident `closed`
  - `infra/stack.py`: `build_asset(service)`, Lambdas `pilotlight-tools`, `pilotlight-session`, `pilotlight-hangup`, role `pilotlight-gateway`, rule `pilotlight-call-ended`, Connect IAM scoped to the instance. Synth verified with aws-cdk-lib 2.273.0.
  - `connect/`: `SETUP.md` (console steps), `agent_prompt.md`, `tool_schema.json`
  - `scripts/connect_setup.py` (gateway, target, Lambda association), `scripts/test_call.py`
  - Mocked handler tests pass. Nothing deployed or called against real AWS yet.

### Not done (in order)
- [ ] `aws login` by Zain (interactive), `cdk bootstrap`, `cdk deploy`
- [ ] Test: traffic → break → alarm ALARM within ~30s → `status.sh` shows incident and timeline rows → fix → alarm OK
- [ ] Box: `box_client.py`, `scripts/box_setup.py`, real `box_tools.py`, `runbooks/checkout-5xx.md` (needs P3's credentials)
- [ ] Incident Lambda dependencies: once `box_tools` imports `box_sdk_gen`, `build_asset()` in `infra/stack.py` must also `pip install box-sdk-gen` into `build/incident/` and `build/hangup/`
- [ ] Connect (P2): instance with Connect Customer + outbound calling, phone number, then `connect/SETUP.md` steps 3 to 11. Put `CONNECT_*` in `.env`, redeploy, `scripts/test_call.py`
- [ ] Verify on a real call: AI agent session exists on the contact (session Lambda timeline row), tools reach `pilotlight-tools`, `ListMessages` returns the caller's "confirm" before the tool call (else tune `caller_confirmed` retries)
- [ ] `pilotlight/postmortem.py`, called from `services/hangup/handler.py`; also write `transcript.md` to Box there
- [ ] Stretch: timeline page. README services list and architecture are already written.

## 4. Decisions already made (do not reopen)

- **Names follow the build plan:** SSM `/pilotlight/checkout/fail_mode`, alarm `pilotlight-checkout-5xx`, tables `pilotlight-timeline` and `pilotlight-incidents`, stack `PilotLight`, functions `pilotlight-checkout` and `pilotlight-incident`. The older `db-mode` and `checkout-5xx-high` names are retired.
- **Region** `us-east-1`. **Python 3.12** everywhere.
- **Lambda packaging:** `infra/stack.py` copies `services/<name>/` and `pilotlight/` into `build/<name>/` at synth time. No Docker bundling. `build/` is gitignored.
- **Incident Lambda env** is read from the repo `.env` at synth time (`PASSTHROUGH_ENV` in `infra/stack.py`). After changing `.env` (for example `CONNECT_CONTACT_FLOW_ID`), run `cdk deploy` again.
- **No retries** on the Incident Lambda (`retry_attempts=0` on both the function and the rule target), so one alarm never places two calls.
- **`what_changed`** pages through all SSM history and speaks the time in Pacific time.
- **Telephony: Amazon Connect, native.** Nova Sonic runs inside Connect as the speech-to-speech model of a Conversational AI bot, with an orchestrator AI agent (copy of `SelfServiceOrchestrator`). Tools reach `pilotlight/tools.py` over MCP: AgentCore Gateway `pilotlight-tools`, Lambda target `pilotlight` (tool names `pilotlight___<tool>`). No voice server, no ngrok, no Twilio. `VOICE_SERVER_URL` and `TWILIO_*` are retired.
- **Confirm check** lives in `services/tools/handler.py`: `confirmed=True` only if the latest CUSTOMER message from `qconnect.list_messages` contains "confirm" without a negation. `REQUIRE_SPOKEN_CONFIRM=false` is an emergency demo switch only.
- **Incident lifecycle:** `open` at alarm, `closed` at hang-up.
- **Alarm** fires on `PilotLight/CheckoutErrors`, Sum over 10s, threshold 3, missing data not breaching.

## 5. Open decisions

- **Box AI Q&A** availability on the developer account. If disabled, `ask_runbook` uses Bedrock over the runbook text.
- **Text model ID** for the postmortem (P2 to confirm in the Bedrock playground).

## 6. Commands

```bash
source .venv/bin/activate
aws login && aws configure set region us-east-1 && aws sts get-caller-identity
cd infra && cdk bootstrap && cdk deploy     # if creds error: eval "$(aws configure export-credentials --format env)"

scripts/traffic.sh        # dots = 200, X = error
scripts/break.sh          # fail_mode on
scripts/status.sh         # flag, alarm state, latest incident timeline
scripts/fix.sh            # fail_mode off
scripts/force_alarm.sh    # only fires if the alarm is not already in ALARM; run fix.sh and wait for OK first

python scripts/connect_setup.py   # after cdk deploy: AgentCore Gateway + target, Lambda association (idempotent)
python scripts/test_call.py       # ring ONCALL_PHONE with a test incident, checkout untouched
```

## 7. Rules

- Never commit `.env` or secrets. Credentials arrive by DM and go only in `.env`.
- Commit after each working step. End commit messages with the `Co-Authored-By` line.
- Do not change the shared contracts (`pilotlight/tools.py` signatures, `contracts/`, table schemas) without telling Zain.
- Ask before anything destructive: `cdk destroy`, any `delete-*`, force pushes.
- If a step blocks for more than 20 minutes, stub it and move on.
- **Writing style** for docs, README, commits, slides: professional, precise, declarative. No filler. **Never use em dashes.**
