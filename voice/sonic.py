"""Nova 2 Sonic speech-to-speech session with tool calling, one per phone call."""
import asyncio
import base64
import json
import uuid
from typing import Awaitable, Callable

import boto3
from aws_sdk_bedrock_runtime.client import AsyncBedrockRuntimeClient
from aws_sdk_bedrock_runtime.config import AsyncBedrockRuntimeConfig
from aws_sdk_bedrock_runtime.models import (BidirectionalInputPayloadPart,
                                            InvokeModelWithBidirectionalStreamInputChunk,
                                            InvokeModelWithBidirectionalStreamOperationInput)
from smithy_aws_core.identity import AWSCredentialsIdentity
from smithy_core.aio.interfaces.identity import IdentityResolver
from smithy_http.aio.crt import AWSCRTHTTPClient

from pilotlight import timeline
from pilotlight.agent import TOOL_SPECS, IncidentAgent, _speakable
from pilotlight.config import SONIC_MODEL_ID, SONIC_REGION

from . import prompt

OUT_RATE = 8000  # Twilio's rate, so no resampling on the way out
VOICE_ID = "matthew"
END_CALL_QUIET_SECONDS = 1.5  # model audio has stopped for this long, so the goodbye is fully generated

END_CALL_SPEC = {"toolSpec": {
    "name": "end_call",
    "description": "Hang up the phone call. Only after the engineer agrees to end the call and you have said goodbye.",
    "inputSchema": {"json": json.dumps({"type": "object", "properties": {}})}}}


class _ProfileCredentials(IdentityResolver):
    """Resolves credentials from the boto3 default chain (AWS_PROFILE from .env) on every request."""

    async def get_identity(self, *, properties=None):
        c = boto3.Session().get_credentials().get_frozen_credentials()
        return AWSCredentialsIdentity(access_key_id=c.access_key, secret_access_key=c.secret_key,
                                      session_token=c.token)


def _sonic_tools() -> list[dict]:
    """The text agent's tool specs, with the JSON schema serialized as Sonic expects."""
    return [{"toolSpec": {**t["toolSpec"], "inputSchema": {"json": json.dumps(t["toolSpec"]["inputSchema"]["json"])}}}
            for t in TOOL_SPECS] + [END_CALL_SPEC]


class SonicSession:
    def __init__(self, incident_id: str,
                 on_audio: Callable[[bytes], Awaitable[None]],
                 on_interrupt: Callable[[], Awaitable[None]] | None = None,
                 on_end: Callable[[], Awaitable[None]] | None = None):
        self.incident_id = incident_id
        self.on_audio, self.on_interrupt, self.on_end = on_audio, on_interrupt, on_end
        self._last_audio = 0.0
        self.transcript: list[str] = []
        self.last_user = ""
        self.closed = False
        self._prompt, self._audio = str(uuid.uuid4()), str(uuid.uuid4())
        self._stages: dict[str, str] = {}
        self._send_lock = asyncio.Lock()
        self._tool_runner = IncidentAgent.__new__(IncidentAgent)  # reuse _run_tool and its confirm gate
        self._tool_runner.incident_id = incident_id

    async def _send(self, event: dict) -> None:
        async with self._send_lock:
            await self._stream.input_stream.send(InvokeModelWithBidirectionalStreamInputChunk(
                value=BidirectionalInputPayloadPart(bytes_=json.dumps({"event": event}).encode())))

    async def _text(self, role: str, text: str, interactive: bool) -> None:
        name = str(uuid.uuid4())
        await self._send({"contentStart": {"promptName": self._prompt, "contentName": name, "type": "TEXT",
                          "interactive": interactive, "role": role,
                          "textInputConfiguration": {"mediaType": "text/plain"}}})
        await self._send({"textInput": {"promptName": self._prompt, "contentName": name, "content": text}})
        await self._send({"contentEnd": {"promptName": self._prompt, "contentName": name}})

    async def start(self) -> None:
        cfg = await AsyncBedrockRuntimeConfig.resolve(
            region=SONIC_REGION, aws_credentials_identity_resolver=_ProfileCredentials(), transport=AWSCRTHTTPClient())
        client = AsyncBedrockRuntimeClient(config=cfg)
        self._stream = await client.invoke_model_with_bidirectional_stream(
            InvokeModelWithBidirectionalStreamOperationInput(model_id=SONIC_MODEL_ID))
        await self._send({"sessionStart": {"inferenceConfiguration": {"maxTokens": 1024, "topP": 0.9, "temperature": 0.7}}})
        await self._send({"promptStart": {
            "promptName": self._prompt,
            "textOutputConfiguration": {"mediaType": "text/plain"},
            "audioOutputConfiguration": {"mediaType": "audio/lpcm", "sampleRateHertz": OUT_RATE, "sampleSizeBits": 16,
                                         "channelCount": 1, "voiceId": VOICE_ID, "encoding": "base64",
                                         "audioType": "SPEECH"},
            "toolUseOutputConfiguration": {"mediaType": "application/json"},
            "toolConfiguration": {"tools": _sonic_tools()}}})
        await self._text("SYSTEM", prompt.build(self.incident_id), interactive=False)
        self._reader = asyncio.create_task(self._read())
        await self._send({"contentStart": {"promptName": self._prompt, "contentName": self._audio, "type": "AUDIO",
                          "interactive": True, "role": "USER",
                          "audioInputConfiguration": {"mediaType": "audio/lpcm", "sampleRateHertz": 16000,
                                                      "sampleSizeBits": 16, "channelCount": 1,
                                                      "audioType": "SPEECH", "encoding": "base64"}}})
        await self._text("USER", prompt.KICKOFF, interactive=True)  # the agent speaks first
        timeline.add(self.incident_id, "call", "Call connected, voice agent started")

    async def send_audio(self, pcm_16k: bytes) -> None:
        if not self.closed:
            await self._send({"audioInput": {"promptName": self._prompt, "contentName": self._audio,
                                             "content": base64.b64encode(pcm_16k).decode()}})

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            await self._send({"contentEnd": {"promptName": self._prompt, "contentName": self._audio}})
            await self._send({"promptEnd": {"promptName": self._prompt}})
            await self._send({"sessionEnd": {}})
            await self._stream.input_stream.close()
        except Exception:
            pass
        try:
            await asyncio.wait_for(self._reader, 5)
        except Exception:
            self._reader.cancel()

    async def _read(self) -> None:
        _, out = await self._stream.await_output()
        while True:
            try:
                r = await out.receive()
            except Exception as e:
                if not self.closed:
                    print(f"[sonic] stream error: {e}")
                return
            if r is None:
                return
            raw = getattr(getattr(r, "value", None), "bytes_", None)
            if raw is None:
                print(f"[sonic] non-payload event: {r!r}"[:300])
                return
            for kind, body in json.loads(raw).get("event", {}).items():
                await self._handle(kind, body)

    async def _handle(self, kind: str, body: dict) -> None:
        if kind == "audioOutput":
            self._last_audio = asyncio.get_running_loop().time()
            await self.on_audio(base64.b64decode(body["content"]))
        elif kind == "contentStart" and body.get("type") == "TEXT":
            fields = json.loads(body.get("additionalModelFields") or "{}")
            self._stages[body.get("contentId", "")] = fields.get("generationStage", "FINAL")
        elif kind == "textOutput":
            text, role = body.get("content", ""), body.get("role")
            if '"interrupted"' in text:
                if self.on_interrupt:
                    await self.on_interrupt()
                return
            if role == "USER":
                if text.strip() == prompt.KICKOFF:
                    return
                self.last_user = text
                self.transcript.append(f"Engineer: {text}")
                await asyncio.to_thread(timeline.add, self.incident_id, "user", text)
            elif role == "ASSISTANT" and self._stages.get(body.get("contentId", ""), "FINAL") == "FINAL":
                text = _speakable(text)
                self.transcript.append(f"Pilot Light: {text}")
                await asyncio.to_thread(timeline.add, self.incident_id, "agent", text)
        elif kind == "toolUse":
            asyncio.create_task(self._tool(body))

    async def _tool(self, body: dict) -> None:
        name, args = body.get("toolName", ""), json.loads(body.get("content") or "{}")
        if name == "end_call":
            result = "Ending the call now."
            asyncio.create_task(self._end_when_quiet())
        else:
            # Code-level confirm gate: _run_tool checks the latest engineer transcript for "confirm"
            self._tool_runner._last_user = self.last_user
            result = await asyncio.to_thread(self._tool_runner._run_tool, name, args)
        content = str(uuid.uuid4())
        await self._send({"contentStart": {"promptName": self._prompt, "contentName": content, "interactive": False,
                          "type": "TOOL", "role": "TOOL",
                          "toolResultInputConfiguration": {"toolUseId": body["toolUseId"], "type": "TEXT",
                                                           "textInputConfiguration": {"mediaType": "text/plain"}}}})
        await self._send({"toolResult": {"promptName": self._prompt, "contentName": content,
                                         "content": json.dumps({"result": result})}})
        await self._send({"contentEnd": {"promptName": self._prompt, "contentName": content}})

    async def _end_when_quiet(self) -> None:
        """Wait until the goodbye has finished generating, then hand off to the caller to hang up."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 15
        await asyncio.sleep(1.0)
        while loop.time() - self._last_audio < END_CALL_QUIET_SECONDS and loop.time() < deadline:
            await asyncio.sleep(0.25)
        await asyncio.to_thread(timeline.add, self.incident_id, "call", "Agent ended the call")
        if self.on_end:
            await self.on_end()
