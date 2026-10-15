"""Alexa+ behavior simulator host: devices, account linking, MCP Apps bridge, inspector."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import AlexaSimSettings
from .devices import Device, DeviceKind, DeviceState
from .mcp_pool import MCPClientPool
from .orchestrator import Orchestrator
from .planners import MockReplay, OllamaPlanner, Planner
from .reply_policy import structured
from .voice import VoiceEngines


FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
LABEL = "Alexa+ behavior simulator for a hackathon demo. Not an Amazon product."
ACCOUNTS = {"maya": "show", "sam": "dot"}


class LinkIn(BaseModel):
    account: str = Field(pattern="^(maya|sam)$")


class UtteranceIn(BaseModel):
    device_id: str = Field(pattern="^(show|dot)$")
    text: str = Field(min_length=1, max_length=600)


class BridgeCall(BaseModel):
    device_id: str = Field(pattern="^(show|dot)$")
    name: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any] = Field(default_factory=dict)


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


MAX_AUDIO_BYTES = 30 * 16_000 * 2  # 30 s of 16 kHz mono PCM16


class PlannerIn(BaseModel):
    mode: str = Field(pattern="^(mock|ollama)$")


def build_planner(settings: AlexaSimSettings, mode: str | None = None) -> Planner:
    mode = mode or settings.planner
    if mode == "ollama" and settings.llm_model:
        return OllamaPlanner(settings.llm_base_url, settings.llm_model, settings.llm_timeout_seconds)
    return MockReplay()


def create_alexa_sim_app(settings: AlexaSimSettings | None = None, pool: MCPClientPool | None = None,
                         planner: Planner | None = None, voice: VoiceEngines | None = None) -> FastAPI:
    settings = settings or AlexaSimSettings.from_env()
    voice = voice or VoiceEngines(settings)
    traces: list[dict[str, Any]] = []
    sockets: set[WebSocket] = set()
    devices = {"show": Device("show", DeviceKind.SHOW, owner="maya"), "dot": Device("dot", DeviceKind.DOT, owner="sam")}
    host_state: dict[str, Any] = {"invitation_id": None}

    async def broadcast(message: dict[str, Any]) -> None:
        for socket in list(sockets):
            try:
                await socket.send_json(message)
            except Exception:
                sockets.discard(socket)

    async def trace(entry: dict[str, Any]) -> None:
        traces.append(entry)
        del traces[:-200]
        await broadcast({"type": "trace", "entry": entry})

    async def device_event(device: Device, **payload: Any) -> None:
        await broadcast(device.event("device", **payload))

    pool = pool or MCPClientPool(settings.mcp_url, trace)
    orchestrator = Orchestrator(pool, planner or build_planner(settings), max_steps=settings.max_tool_steps, trace=trace)

    async def sync_caregiver_notifications() -> None:
        """Simulated push: Alexa+ MCP add-ons have no documented server push, so the
        host polls the caregiver's generic notification tool and lights the Dot ring."""
        dot = devices["dot"]
        if not pool.linked(dot.account):
            dot.notification = False
        else:
            result = await pool.call_tool(dot.account, "list_generic_notifications", {}, source="push-sim")
            refs = structured(result).get("refs") or [] if not result["isError"] else []
            dot.notification = any(ref.get("status") == "action_required" for ref in refs)
        await device_event(dot)

    def remember_invitation(turn) -> None:
        """Model the invitation link Maya's invite would send to Sam out of band."""
        for name, data in turn.results:
            if name == "invite_caregiver" and data.get("refs"):
                host_state["invitation_id"] = data["refs"][0]["id"]

    def device_account(device_id: str) -> str:
        device = devices[device_id]
        if not pool.linked(device.account):
            raise HTTPException(401, "Enable CareLoop for this device first")
        return device.account  # type: ignore[return-value]

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.pool, app.state.devices = pool, devices
        voice.warm_in_background()
        yield
        await pool.close()

    app = FastAPI(title="CareLoop Alexa+ behavior simulator", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(FRONTEND / "index.html")

    @app.get("/api/state")
    async def state() -> dict[str, Any]:
        return {
            "label": LABEL,
            "planner": orchestrator.planner.name,
            "invitation_pending": bool(host_state["invitation_id"]),
            "devices": [{"id": d.id, "kind": d.kind, "owner": d.owner, "account": d.account, "state": d.state,
                         "notification": d.notification, "pending": bool(d.pending)} for d in devices.values()],
            "trace": traces[-60:],
            "tools": {account: [t["name"] for t in session.model_tools] for account, session in pool.accounts.items()},
        }

    @app.post("/api/link")
    async def link(body: LinkIn) -> dict[str, Any]:
        try:
            session = await pool.link(body.account, settings.token_for(body.account))
        except Exception as exc:
            raise HTTPException(502, "CareLoop account linking failed. Is the CareLoop server running?") from exc
        device = devices[ACCOUNTS[body.account]]
        device.account = body.account
        await sync_caregiver_notifications()
        return {"linked": body.account, "device_id": device.id, "tools": [t["name"] for t in session.model_tools]}

    @app.post("/api/unlink/{account}")
    async def unlink(account: str) -> dict[str, bool]:
        if account not in ACCOUNTS:
            raise HTTPException(404, "Unknown account")
        await pool.unlink(account)
        device = devices[ACCOUNTS[account]]
        if device.awaiting is not None and not device.awaiting.question.answer.done():
            device.awaiting.question.answer.set_result({"action": "cancel"})
        device.account, device.pending, device.history, device.disclaimed, device.awaiting = None, None, [], False, None
        await sync_caregiver_notifications()
        return {"unlinked": True}

    @app.post("/api/invite/open")
    async def open_invitation() -> dict[str, Any]:
        """Sam opens the invitation link Maya's invite produced (delivered out of band)."""
        invitation_id = host_state["invitation_id"]
        if not invitation_id:
            raise HTTPException(404, "No invitation has been sent yet")
        account = device_account("dot")
        result = await pool.call_tool(account, "accept_caregiver_invitation", {"invitation_id": invitation_id}, source="invite-link")
        host_state["invitation_id"] = None
        await sync_caregiver_notifications()
        reply = structured(result).get("speakable") if not result["isError"] else "That invitation is no longer available."
        return {"accepted": not result["isError"], "reply": reply}

    @app.post("/api/planner")
    async def set_planner(body: PlannerIn) -> dict[str, str]:
        orchestrator.planner = build_planner(settings, body.mode)
        orchestrator.fallback = None if isinstance(orchestrator.planner, MockReplay) else MockReplay()
        return {"planner": orchestrator.planner.name}

    @app.post("/api/utterance")
    async def utterance(body: UtteranceIn) -> dict[str, Any]:
        device = devices[body.device_id]
        device.state = DeviceState.THINKING
        await device_event(device)
        try:
            turn = await orchestrator.respond(device, body.text)
        except Exception as exc:
            await trace({"type": "turn_error", "device_id": device.id, "error": type(exc).__name__})
            device.awaiting = None
            return {"reply": "Sorry, CareLoop is having trouble right now. Please try again.", "tools": [],
                    "screen": None, "needs_confirmation": False, "expects_reply": False,
                    "planner": orchestrator.planner.name}
        finally:
            device.state = DeviceState.IDLE
            await device_event(device)
        if device.account == "maya":
            remember_invitation(turn)
        if turn.tools:
            await sync_caregiver_notifications()
        await trace({"type": "turn", "device_id": device.id, "planner": turn.planner, "tools": turn.tools,
                     "reply": turn.reply, "needs_confirmation": turn.needs_confirmation})
        return {"reply": turn.reply, "tools": turn.tools, "screen": turn.screen,
                "needs_confirmation": turn.needs_confirmation, "expects_reply": turn.expects_reply,
                "planner": turn.planner}

    @app.post("/api/conversation/reset")
    async def reset_conversation() -> dict[str, bool]:
        for device in devices.values():
            if device.awaiting is not None and not device.awaiting.question.answer.done():
                device.awaiting.question.answer.set_result({"action": "cancel"})
            device.history, device.pending, device.disclaimed, device.awaiting = [], None, False, None
        return {"reset": True}

    # ---- local speech (Kokoro TTS / Whisper STT); the browser falls back on 404/503 -----
    @app.get("/api/voice")
    async def voice_config() -> dict[str, Any]:
        return voice.describe()

    @app.post("/api/tts")
    async def tts(body: SpeakIn) -> Response:
        if voice.tts is None:
            raise HTTPException(404, "Browser speech synthesis is active")
        try:
            audio = await asyncio.to_thread(voice.tts.synthesize, body.text)
        except Exception as exc:
            raise HTTPException(503, "Local speech output is unavailable") from exc
        return Response(audio, media_type="audio/wav")

    @app.post("/api/stt")
    async def stt(request: Request) -> dict[str, str]:
        if voice.stt is None:
            raise HTTPException(404, "Browser speech recognition is active")
        audio = await request.body()
        if len(audio) > MAX_AUDIO_BYTES:
            raise HTTPException(413, "Audio is limited to 30 seconds")
        try:
            text = await asyncio.to_thread(voice.stt.transcribe, audio, 16_000)
        except Exception as exc:
            raise HTTPException(503, "Local speech recognition is unavailable") from exc
        return {"text": text}

    # ---- MCP Apps host bridge (credentials stay in this process) -------------
    @app.get("/api/apps/resource")
    async def app_resource(device_id: str, uri: str) -> dict[str, str]:
        if device_id != "show":
            raise HTTPException(403, "Voice-only devices do not render private views")
        account = device_account(device_id)
        declared = {((t.get("_meta") or {}).get("ui") or {}).get("resourceUri") for t in pool.accounts[account].tools}
        if uri not in declared:
            raise HTTPException(404, "Private app resource is unavailable")
        return {"html": await pool.read_resource(account, uri)}

    @app.post("/api/apps/call")
    async def app_call(body: BridgeCall) -> dict[str, Any]:
        if body.device_id != "show":
            raise HTTPException(403, "Voice-only devices do not render private views")
        account = device_account(body.device_id)
        if body.name not in {t["name"] for t in pool.accounts[account].tools}:
            raise HTTPException(404, "Unknown CareLoop tool")
        result = await pool.call_tool(account, body.name, body.arguments, source="app")
        if body.name != "get_private_view":
            await sync_caregiver_notifications()
        return {"structuredContent": result["structuredContent"], "content": result["content"], "isError": result["isError"]}

    @app.websocket("/ws")
    async def websocket(socket: WebSocket) -> None:
        await socket.accept()
        sockets.add(socket)
        try:
            while True:
                await socket.receive_text()
        except WebSocketDisconnect:
            sockets.discard(socket)

    return app
