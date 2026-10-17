"""Voice server: places the on-call call through Twilio and bridges the Media Stream to Nova 2 Sonic.

Run: uvicorn voice.server:app --port 8000   (expose with ngrok, set VOICE_SERVER_URL)
"""
import asyncio
import base64
import json
from urllib.parse import urlencode
from xml.sax.saxutils import quoteattr

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response

from pilotlight import incidents, postmortem, timeline
from pilotlight.config import (ONCALL_PHONE, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN,
                               TWILIO_FROM_NUMBER, VOICE_SERVER_URL)

from .audio import Converter
from .sonic import SonicSession

FRAME = 160  # 20ms of 8 kHz mu-law

app = FastAPI(title="Pilot Light voice server")


@app.get("/health")
async def health():
    return {"ok": True, "twilio_configured": bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN)}


@app.post("/call")
async def call(body: dict):
    iid = body["incident_id"]
    missing = [k for k, v in {"TWILIO_ACCOUNT_SID": TWILIO_ACCOUNT_SID, "TWILIO_AUTH_TOKEN": TWILIO_AUTH_TOKEN,
                              "TWILIO_FROM_NUMBER": TWILIO_FROM_NUMBER, "ONCALL_PHONE": ONCALL_PHONE,
                              "VOICE_SERVER_URL": VOICE_SERVER_URL}.items() if not v]
    if missing:
        return JSONResponse(status_code=503, content={"error": f"Twilio not configured, missing: {', '.join(missing)}"})
    from twilio.rest import Client
    # Twilio fetches the TwiML from /twiml; trial accounts reject inline twiml on calls.create
    c = await asyncio.to_thread(Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN).calls.create,
                                to=ONCALL_PHONE, from_=TWILIO_FROM_NUMBER,
                                url=f"{VOICE_SERVER_URL}/twiml?{urlencode({'incident_id': iid})}")
    return {"call_sid": c.sid}


@app.api_route("/twiml", methods=["GET", "POST"])
async def twiml(incident_id: str):
    ws_url = VOICE_SERVER_URL.replace("https://", "wss://") + "/media"
    xml = (f"<?xml version=\"1.0\" encoding=\"UTF-8\"?><Response><Connect><Stream url={quoteattr(ws_url)}>"
           f"<Parameter name=\"incident_id\" value={quoteattr(incident_id)}/></Stream></Connect></Response>")
    return Response(content=xml, media_type="application/xml")


@app.websocket("/media")
async def media(ws: WebSocket):
    await ws.accept()
    conv, session, stream_sid, iid = Converter(), None, None, None

    async def to_twilio(pcm: bytes) -> None:
        ulaw = conv.sonic_to_twilio(pcm)
        for i in range(0, len(ulaw), FRAME):
            await ws.send_text(json.dumps({"event": "media", "streamSid": stream_sid,
                                           "media": {"payload": base64.b64encode(ulaw[i:i + FRAME]).decode()}}))

    async def barge_in() -> None:
        await ws.send_text(json.dumps({"event": "clear", "streamSid": stream_sid}))

    try:
        while True:
            msg = json.loads(await ws.receive_text())
            event = msg.get("event")
            if event == "start":
                stream_sid = msg["start"]["streamSid"]
                iid = msg["start"].get("customParameters", {}).get("incident_id") or (incidents.latest() or {}).get("incident_id")
                print(f"[voice] call started for {iid}")
                session = SonicSession(iid, to_twilio, barge_in)
                await session.start()
            elif event == "media" and session:
                await session.send_audio(conv.twilio_to_sonic(base64.b64decode(msg["media"]["payload"])))
            elif event == "stop":
                break
    except WebSocketDisconnect:
        pass
    finally:
        if session:
            await session.close()
            await asyncio.to_thread(_finish, iid, list(session.transcript))


def _finish(iid: str, transcript: list[str]) -> None:
    timeline.add(iid, "call", "Call ended")
    folder_id = (incidents.get(iid) or {}).get("box_folder_id", "")
    try:
        postmortem.generate(iid, folder_id, "\n".join(transcript))
        print(f"[voice] postmortem written for {iid}")
    except Exception as e:
        print(f"[voice] postmortem failed for {iid}: {e}")
