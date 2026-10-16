"""Alexa+ behavior simulator host: devices, account linking, MCP Apps bridge, inspector."""
from __future__ import annotations

import asyncio
import json
import time
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
from .reply_policy import speakable, structured
from .voice import VoiceEngines


FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
SAMPLES = Path(__file__).resolve().parents[3] / "samples"
SAMPLE_FILES = {"typed": "prescription_typed.pdf", "scanned": "prescription_scanned.pdf",
                "photo": "prescription_photo.png", "injection": "prompt_injection.pdf"}
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
    host_state: dict[str, Any] = {"invitation_id": None, "reminders": [], "last_used": time.monotonic(), "used": False}

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

    async def announce(device_id: str, reply: str, screen: dict[str, Any] | None = None) -> None:
        """Speak on a device without a user turn (document ready, invite accepted, …)."""
        await trace({"type": "turn", "device_id": device_id, "planner": "host", "tools": [], "reply": reply,
                     "needs_confirmation": False})
        await broadcast({"type": "announce", "device_id": device_id, "reply": reply, "screen": screen})

    def careloop_http(method: str, path: str, account: str, body: bytes | None = None,
                      content_type: str | None = None) -> dict[str, Any]:
        """Server-side call to CareLoop's REST API with the account's credential (never sent to the browser)."""
        from urllib.error import HTTPError
        from urllib.request import Request as UrlRequest, urlopen
        headers = {"Authorization": f"Bearer {settings.token_for(account)}"}
        if content_type:
            headers["Content-Type"] = content_type
        request = UrlRequest(settings.server_url + path, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=30) as response:  # noqa: S310 - configured local CareLoop URL
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = json.loads(exc.read().decode("utf-8") or "{}").get("detail", "CareLoop refused the document")
            raise HTTPException(exc.code, detail) from exc

    async def watch_intake(account: str, job_id: str) -> None:
        """Poll the job; when it's ready, Maya's Show announces it and opens the review screen."""
        for _ in range(200):
            await asyncio.sleep(1.5)
            try:
                job = (await asyncio.to_thread(careloop_http, "GET", f"/api/care/intake/{job_id}", account))["job"]
            except Exception:
                continue
            if job["status"] == "processing":
                continue
            show = devices["show"]
            if pool.linked(show.account):
                result = await pool.call_tool(show.account, "get_intake_status", {})
                reply = speakable(result) or "Your document has been processed."
                data = structured(result)
                screen = ({"tool": "get_intake_status", "resource_uri": data["view"],
                           "result": {"structuredContent": data, "isError": False}}
                          if not result["isError"] and data.get("view") else None)
                await announce("show", reply, screen)
            await sync_caregiver_notifications()
            return

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

    async def remember_reminders(results: list[dict[str, Any]]) -> None:
        """Alexa+ would create these with its own reminders feature; the simulator keeps them for the Director."""
        for data in results:
            for reminder in data.get("reminders") or []:
                # One reminder per task, for whoever currently owns it (reassigning replaces it).
                host_state["reminders"] = [r for r in host_state["reminders"] if r["task_id"] != reminder["task_id"]]
                host_state["reminders"].append(reminder)
                who = "Maya" if reminder["to"] == "patient" else reminder["to"]
                await trace({"type": "host", "text": f"Alexa+ reminder set for {who}: '{reminder['label']}' at "
                                                     f"{', '.join(reminder['times'])} (simulated native reminder)"})

    INVITE_NOTICE = "Maya invited you to help with her care in CareLoop. Open the invitation in your Alexa app to accept."

    def remember_invitation(turn) -> bool:
        """Model the invitation link Maya's invite would send to Sam out of band. True if a new one was sent."""
        sent = False
        for name, data in turn.results:
            if name == "invite_caregiver" and data.get("refs"):
                host_state["invitation_id"] = data["refs"][0]["id"]
                sent = True
        return sent

    async def tell_sam_about_invitation() -> None:
        """Simulated notice on Sam's own Dot: who invited him, nothing about permissions or health."""
        if host_state["invitation_id"] and pool.linked(devices["dot"].account):
            await announce("dot", INVITE_NOTICE)

    def device_account(device_id: str) -> str:
        device = devices[device_id]
        if not pool.linked(device.account):
            raise HTTPException(401, "Enable CareLoop for this device first")
        return device.account  # type: ignore[return-value]

    async def reset_demo() -> dict[str, Any]:
        """Shared demo: CareLoop wipes and reseeds the demo patient; both devices start over, linked."""
        seeded = (await asyncio.to_thread(careloop_http, "POST", "/api/care/demo/reset", "maya"))["seeded"]
        for device in devices.values():
            device.forget_conversation()
        host_state.update(invitation_id=None, reminders=[], last_used=time.monotonic(), used=False)
        traces.clear()
        for account, device_id in ACCOUNTS.items():
            await pool.link(account, settings.token_for(account))
            devices[device_id].account = account
        await sync_caregiver_notifications()
        await broadcast({"type": "reset"})
        await trace({"type": "host", "text": "Demo reset: synthetic starting data restored, Maya and Sam linked"})
        return seeded

    async def reset_when_idle() -> None:
        while True:
            await asyncio.sleep(min(30.0, settings.idle_reset_minutes * 60))
            idle = time.monotonic() - host_state["last_used"]
            if host_state["used"] and idle >= settings.idle_reset_minutes * 60:
                try:
                    await reset_demo()
                except Exception as exc:
                    await trace({"type": "host", "text": f"Idle demo reset failed ({type(exc).__name__})"})
                    host_state["last_used"] = time.monotonic()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.pool, app.state.devices = pool, devices
        voice.warm_in_background()
        idle_task = asyncio.create_task(reset_when_idle()) if settings.idle_reset_minutes > 0 else None
        yield
        if idle_task:
            idle_task.cancel()
        await pool.close()

    app = FastAPI(title="CareLoop Alexa+ behavior simulator", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")

    @app.middleware("http")
    async def note_use(request: Request, call_next):
        """Anything a visitor does to the demo postpones the idle reset."""
        if request.method == "POST" and request.url.path not in {"/api/demo/reset", "/api/tts", "/api/stt"}:
            host_state.update(last_used=time.monotonic(), used=True)
        return await call_next(request)

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(FRONTEND / "index.html")

    @app.get("/api/state")
    async def state() -> dict[str, Any]:
        return {
            "label": LABEL,
            "planner": orchestrator.planner.name,
            "invitation_pending": bool(host_state["invitation_id"]),
            "privacy_url": f"{settings.server_url}/privacy", "terms_url": f"{settings.server_url}/terms",
            "reminders": host_state["reminders"],
            "idle_reset_minutes": settings.idle_reset_minutes,
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
        if body.account == "sam":
            await tell_sam_about_invitation()  # an invitation sent before Sam linked his Dot
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

    @app.post("/api/documents/share")
    async def share_document(request: Request, account: str, title: str = "Clinic document",
                             doc_type: str | None = None, sample: str | None = None) -> dict[str, Any]:
        """The Alexa app's 'share a file' flow: Maya, or Sam if she let him upload, sends a document to CareLoop."""
        if account not in ACCOUNTS:
            raise HTTPException(404, "Unknown account")
        if sample:
            if sample not in SAMPLE_FILES or not (SAMPLES / SAMPLE_FILES[sample]).is_file():
                raise HTTPException(404, "Sample not found; run: uv run python evals/intake/documents.py")
            data = (SAMPLES / SAMPLE_FILES[sample]).read_bytes()
        else:
            data = await request.body()
        if not data:
            raise HTTPException(422, "Choose a file to share")
        from urllib.parse import urlencode
        query = urlencode({k: v for k, v in {"title": title, "doc_type": doc_type}.items() if v})
        await trace({"type": "host", "text": f"{account} shared a document with CareLoop ({len(data)} bytes)"})
        out = await asyncio.to_thread(careloop_http, "POST", f"/api/care/documents/upload?{query}", account, data,
                                      "application/octet-stream")
        job = out["job"]
        asyncio.create_task(watch_intake(account, job["id"]))
        if account == "sam":
            await announce("dot", "Thanks. I've sent it to Maya to review.")
        return {"job": job}

    @app.post("/api/reminders/ring")
    async def ring_reminder() -> dict[str, Any]:
        """Director: fire the next simulated Alexa+ reminder on the right device."""
        if not host_state["reminders"]:
            raise HTTPException(404, "No reminders are set")
        reminder = host_state["reminders"].pop(0)
        if reminder["to"] == "patient":
            await announce("show", f"Reminder: {reminder['label']}.")
        else:
            await announce("dot", f"Reminder for {reminder['to']}: Maya's {reminder['label']}.")
        return {"rang": reminder, "remaining": len(host_state["reminders"])}

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
            await trace({"type": "turn_error", "device_id": device.id, "heard": body.text, "error": type(exc).__name__})
            device.awaiting = None
            return {"reply": "Sorry, CareLoop is having trouble right now. Please try again.", "tools": [],
                    "screen": None, "needs_confirmation": False, "expects_reply": False,
                    "planner": orchestrator.planner.name}
        finally:
            device.state = DeviceState.IDLE
            await device_event(device)
        if device.account == "maya" and remember_invitation(turn):
            await tell_sam_about_invitation()
        await remember_reminders([data for _name, data in turn.results])
        if turn.tools:
            await sync_caregiver_notifications()
        # "heard" is the exact text the device understood. It is what to check when an answer is not accepted.
        await trace({"type": "turn", "device_id": device.id, "planner": turn.planner, "tools": turn.tools,
                     "heard": body.text, "reply": turn.reply, "needs_confirmation": turn.needs_confirmation})
        return {"reply": turn.reply, "tools": turn.tools, "screen": turn.screen,
                "needs_confirmation": turn.needs_confirmation, "expects_reply": turn.expects_reply,
                "planner": turn.planner}

    @app.post("/api/conversation/reset")
    async def reset_conversation() -> dict[str, bool]:
        for device in devices.values():
            device.forget_conversation()
        return {"reset": True}

    @app.post("/api/demo/reset")
    async def demo_reset() -> dict[str, Any]:
        try:
            seeded = await reset_demo()
        except HTTPException as exc:
            if exc.status_code == 404:
                raise HTTPException(409, "Demo reset is off. Start CareLoop with CARELOOP_DEMO_RESET=true.") from exc
            raise
        except OSError as exc:
            raise HTTPException(502, "CareLoop isn't reachable. Is the server running?") from exc
        return {"reset": True, "seeded": seeded}

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
            await remember_reminders([result["structuredContent"] or {}])
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
