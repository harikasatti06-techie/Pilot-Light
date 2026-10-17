"""Operator dashboard: login, live status, incidents with timelines, and console links.
Reads the same local state and CloudWatch Logs groups as the rest of the system; it never
changes anything, so it is safe to leave open on the projector.

Run: uvicorn dashboard.app:app --port 8001   then open http://localhost:8001
"""
import base64
import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse

from pilotlight import flags, incidents, logstore, timeline
from pilotlight.config import (ALARM_NAME, ALARM_THRESHOLD, ALARM_WINDOW_SECONDS, AWS_REGION,
                               BOX_INCIDENTS_FOLDER_ID, BOX_RUNBOOKS_FOLDER_ID, CHECKOUT_LOG_GROUP,
                               CONFIG_AUDIT_LOG_GROUP, DASHBOARD_PASSWORD, DASHBOARD_SECRET,
                               DASHBOARD_USER, INCIDENTS_LOG_GROUP, SONIC_REGION, STATE_DIR,
                               TIMELINE_LOG_GROUP, VOICE_SERVER_URL)

STATIC = Path(__file__).parent / "static"
COOKIE = "pl_session"
SESSION_SECONDS = 12 * 3600
# Without DASHBOARD_SECRET, sessions last until the server restarts
_secret = (DASHBOARD_SECRET or secrets.token_hex(32)).encode()

app = FastAPI(title="Pilot Light dashboard")


def _sign(payload: str) -> str:
    return hmac.new(_secret, payload.encode(), hashlib.sha256).hexdigest()


def _make_token(user: str) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"u": user, "exp": int(time.time()) + SESSION_SECONDS}).encode()).decode()
    return f"{payload}.{_sign(payload)}"


def current_user(request: Request) -> str:
    token = request.cookies.get(COOKIE, "")
    payload, _, sig = token.partition(".")
    if not payload or not hmac.compare_digest(sig, _sign(payload)):
        raise HTTPException(status_code=401, detail="not signed in")
    data = json.loads(base64.urlsafe_b64decode(payload))
    if data["exp"] < time.time():
        raise HTTPException(status_code=401, detail="session expired")
    return data["u"]


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.post("/api/login")
async def login(body: dict, response: Response):
    ok_user = hmac.compare_digest(str(body.get("username", "")), DASHBOARD_USER)
    ok_pass = hmac.compare_digest(str(body.get("password", "")), DASHBOARD_PASSWORD)
    if not (ok_user and ok_pass):
        raise HTTPException(status_code=401, detail="invalid username or password")
    response.set_cookie(COOKIE, _make_token(DASHBOARD_USER), max_age=SESSION_SECONDS, httponly=True, samesite="strict")
    return {"user": DASHBOARD_USER}


@app.post("/api/logout")
async def logout(response: Response):
    response.delete_cookie(COOKIE)
    return {"ok": True}


@app.get("/api/me")
async def me(user: str = Depends(current_user)):
    return {"user": user}


def _alarm_state() -> str:
    p = Path(STATE_DIR) / "alarm_state"
    return p.read_text().strip() if p.exists() else "UNKNOWN"


def _all_incidents() -> list[dict]:
    if not incidents.DIR.exists():
        return []
    return [json.loads(p.read_text()) for p in sorted(incidents.DIR.glob("INC-*.json"), reverse=True)]


@app.get("/api/status")
async def status(user: str = Depends(current_user)):
    all_inc = _all_incidents()
    return {
        "fail_mode": flags.get(), "alarm_name": ALARM_NAME, "alarm_state": _alarm_state(),
        "alarm_rule": f">= {ALARM_THRESHOLD} errors in {ALARM_WINDOW_SECONDS}s",
        "incidents_total": len(all_inc),
        "incidents_open": sum(1 for i in all_inc if i.get("status") == "open"),
        "latest": all_inc[0] if all_inc else None,
        "voice_server": bool(VOICE_SERVER_URL),
    }


@app.get("/api/incidents")
async def list_incidents(user: str = Depends(current_user)):
    return _all_incidents()


@app.get("/api/incidents/{incident_id}")
async def incident_detail(incident_id: str, user: str = Depends(current_user)):
    rec = incidents.get(incident_id)
    if not rec:
        raise HTTPException(status_code=404, detail="incident not found")
    return {"incident": rec, "timeline": _safe(lambda: timeline.list_all(incident_id), []),
            "links": {"timeline_logs": _log_stream_url(TIMELINE_LOG_GROUP, incident_id),
                      "box_folder": f"https://app.box.com/folder/{rec['box_folder_id']}" if rec.get("box_folder_id") else ""}}


@app.get("/api/events")
async def events(minutes: int = 15, user: str = Depends(current_user)):
    """Checkout errors bucketed per 30s, plus a merged feed of errors and config changes."""
    minutes = max(1, min(minutes, 60))
    now_ms = int(time.time() * 1000)
    errors = _safe(lambda: logstore.recent(CHECKOUT_LOG_GROUP, minutes * 60, '"ERROR"'), None)
    changes = _safe(lambda: logstore.recent(CONFIG_AUDIT_LOG_GROUP, 24 * 3600), [])
    connected = errors is not None
    errors = errors or []
    bucket_ms, n = 30_000, minutes * 2
    buckets = [0] * n
    for e in errors:
        i = n - 1 - (now_ms - e["timestamp"]) // bucket_ms
        if 0 <= i < n:
            buckets[i] += 1
    feed = [{"ts": e["timestamp"], "kind": "error", "text": e["message"]} for e in errors[-50:]]
    feed += [{"ts": e["timestamp"], "kind": "config", "text": _config_text(e["message"])} for e in changes[-50:]]
    feed.sort(key=lambda r: r["ts"], reverse=True)
    return {"bucket_seconds": bucket_ms // 1000, "error_buckets": buckets, "errors_total": len(errors),
            "feed": feed[:60], "aws_connected": connected}


def _safe(fn, default):
    """Hosted without AWS credentials (for example on Vercel), CloudWatch reads return empty data."""
    try:
        return fn()
    except Exception as e:
        print(f"[dashboard] CloudWatch read failed: {e}")
        return default


def _config_text(message: str) -> str:
    try:
        r = json.loads(message)
        return f"{r['parameter']}: {r['from']} -> {r['to']} by {r['by']}"
    except (ValueError, KeyError):
        return message


def _console(region: str, fragment: str) -> str:
    return f"https://{region}.console.aws.amazon.com/cloudwatch/home?region={region}#{fragment}"


def _enc(s: str) -> str:
    # The CloudWatch console double-encodes path segments in the hash, with $ standing in for %
    return quote(quote(s, safe=""), safe="").replace("%", "$")


def _log_group_url(group: str) -> str:
    return _console(AWS_REGION, f"logsV2:log-groups/log-group/{_enc(group)}")


def _log_stream_url(group: str, stream: str) -> str:
    return _console(AWS_REGION, f"logsV2:log-groups/log-group/{_enc(group)}/log-events/{_enc(stream)}")


@app.get("/api/links")
async def links(user: str = Depends(current_user)):
    r = AWS_REGION
    groups = [(CHECKOUT_LOG_GROUP, "Checkout service logs"), (CONFIG_AUDIT_LOG_GROUP, "Config audit (what changed)"),
              (TIMELINE_LOG_GROUP, "Incident timelines"), (INCIDENTS_LOG_GROUP, "Incident records")]
    sections = [
        {"title": "CloudWatch Logs", "links": [{"label": label, "detail": g, "url": _log_group_url(g)} for g, label in groups] + [
            {"label": "Live Tail", "detail": "Stream checkout logs in real time", "url": _console(r, "logsV2:live-tail")},
            {"label": "Logs Insights", "detail": "Query across log groups", "url": _console(r, "logsV2:logs-insights")},
        ]},
        {"title": "Audit and models", "links": [
            {"label": "CloudTrail event history", "detail": "Who did what in the account",
             "url": f"https://{r}.console.aws.amazon.com/cloudtrailv2/home?region={r}#/events"},
            {"label": "Bedrock (Nova 2 Lite)", "detail": r, "url": f"https://{r}.console.aws.amazon.com/bedrock/home?region={r}#/"},
            {"label": "Bedrock (Nova 2 Sonic)", "detail": SONIC_REGION,
             "url": f"https://{SONIC_REGION}.console.aws.amazon.com/bedrock/home?region={SONIC_REGION}#/"},
        ]},
        {"title": "Box", "links": [
            {"label": "Incidents folder", "detail": "Briefings, transcripts, postmortems",
             "url": f"https://app.box.com/folder/{BOX_INCIDENTS_FOLDER_ID}" if BOX_INCIDENTS_FOLDER_ID else ""},
            {"label": "Runbooks folder", "detail": "Runbooks found by metadata",
             "url": f"https://app.box.com/folder/{BOX_RUNBOOKS_FOLDER_ID}" if BOX_RUNBOOKS_FOLDER_ID else ""},
            {"label": "My tasks", "detail": "Postmortem review tasks", "url": "https://app.box.com/tasks"},
        ]},
        {"title": "Telephony", "links": [
            {"label": "Twilio call logs", "detail": "Every on-call call", "url": "https://console.twilio.com/us1/monitor/logs/calls"},
            {"label": "Voice server health", "detail": VOICE_SERVER_URL or "VOICE_SERVER_URL not set",
             "url": f"{VOICE_SERVER_URL}/health" if VOICE_SERVER_URL else ""},
        ]},
    ]
    return {"sections": sections}
