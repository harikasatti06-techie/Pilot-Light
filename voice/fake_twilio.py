"""Local stand-in for a Twilio Media Stream, for testing the voice server without a phone.

Run: python -m voice.fake_twilio INCIDENT_ID [--url ws://localhost:8000/media] [--out call.wav]
Speaks a scripted call with macOS `say`, records the agent's audio to a wav, and prints timings.
"""
import argparse
import asyncio
import audioop
import base64
import json
import subprocess
import tempfile
import time
import wave
from pathlib import Path

import websockets

SCRIPT = ["What changed?", "Revert it.", "Confirm."]
FRAME = 160          # 20ms of 8 kHz mu-law
SILENCE = b"\xff" * FRAME
QUIET_SECONDS = 2.0  # agent turn is over after this long without audio


def speech(text: str, tmp: Path) -> bytes:
    aiff, wav = tmp / "q.aiff", tmp / "q.wav"
    subprocess.run(["say", "-o", str(aiff), text], check=True)
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@8000", "-c", "1", str(aiff), str(wav)], check=True)
    with wave.open(str(wav)) as w:
        return audioop.lin2ulaw(w.readframes(w.getnframes()), 2)


async def main(iid: str, url: str, out: str) -> None:
    tmp = Path(tempfile.mkdtemp())
    clips = [speech(t, tmp) for t in SCRIPT]
    received, counts = bytearray(), {}
    state = {"last_audio": 0.0, "first_audio": None, "turn_first": None}
    t0 = time.time()

    async with websockets.connect(url) as ws:
        await ws.send(json.dumps({"event": "connected", "protocol": "Call"}))
        await ws.send(json.dumps({"event": "start", "streamSid": "MZfake", "start": {
            "streamSid": "MZfake", "callSid": "CAfake", "customParameters": {"incident_id": iid},
            "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1}}}))

        async def recv():
            async for raw in ws:
                m = json.loads(raw)
                counts[m["event"]] = counts.get(m["event"], 0) + 1
                if m["event"] == "media":
                    received.extend(base64.b64decode(m["media"]["payload"]))
                    state["last_audio"] = time.time()
                    if state["first_audio"] is None:
                        state["first_audio"] = time.time()
                    if state.get("turn_first") is None and time.time() > state.get("mark", 1e18):
                        state["turn_first"] = time.time()

        rtask = asyncio.create_task(recv())

        async def stream(data: bytes, seconds: float | None = None):
            """Send audio in real-time 20ms frames; with seconds, send that much silence instead."""
            frames = [data[i:i + FRAME].ljust(FRAME, b"\xff") for i in range(0, len(data), FRAME)] if data \
                else [SILENCE] * int(seconds / 0.02)
            for f in frames:
                await ws.send(json.dumps({"event": "media", "streamSid": "MZfake",
                                          "media": {"payload": base64.b64encode(f).decode()}}))
                await asyncio.sleep(0.02)

        async def wait_for_agent(since: float, timeout: float = 30) -> float | None:
            """Keep the line open with silence until the agent has spoken and gone quiet."""
            while time.time() - since < timeout:
                await stream(b"", 0.2)
                if state["last_audio"] > since and time.time() - state["last_audio"] > QUIET_SECONDS:
                    return state["last_audio"]
            return None

        start = time.time()
        await wait_for_agent(start)
        print(f"briefing: first audio {state['first_audio'] - t0:.2f}s after connect")
        for text, clip in zip(SCRIPT, clips):
            await stream(clip)
            asked = state["mark"] = time.time()
            state["turn_first"] = None
            await wait_for_agent(asked)
            first = state["turn_first"]
            print(f"asked {text!r}: " + (f"first agent audio {first - asked:.2f}s after question ended" if first else "NO AUDIO"))
        await ws.send(json.dumps({"event": "stop", "streamSid": "MZfake"}))
        await asyncio.sleep(0.5)
        rtask.cancel()

    with wave.open(out, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000)
        w.writeframes(audioop.ulaw2lin(bytes(received), 2))
    print(json.dumps({"events": counts, "agent_audio_seconds": round(len(received) / 8000, 1), "wav": out}))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("incident_id")
    ap.add_argument("--url", default="ws://localhost:8000/media")
    ap.add_argument("--out", default="call.wav")
    a = ap.parse_args()
    asyncio.run(main(a.incident_id, a.url, a.out))
