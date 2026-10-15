"""Local browser voice simulator. It is not an Alexa+ account integration or certification."""
from __future__ import annotations
import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .voice_agent import CareLoopVoiceAgent
from .voice_config import VoiceSimSettings
from .voice_hub import CareLoopMCP
FRONTEND=Path(__file__).resolve().parents[2]/"frontend"
class ChatIn(BaseModel): session_id:str=Field(default="private-demo",max_length=64); persona:str=Field(default="patient",pattern="^(patient|caregiver)$"); text:str=Field(min_length=1,max_length=500)
class SpeakIn(BaseModel): text:str=Field(min_length=1,max_length=6000)

def create_voice_app(settings:VoiceSimSettings|None=None, hub:CareLoopMCP|None=None)->FastAPI:
    settings=settings or VoiceSimSettings.from_env(); hub=hub or CareLoopMCP(settings)
    voice=listener=None
    if settings.voice=="kokoro":
        from .local_voice import KokoroVoice; voice=KokoroVoice(settings.kokoro_voice,settings.kokoro_speed)
    if settings.stt=="whisper":
        from .local_voice import WhisperListener;listener=WhisperListener(settings.whisper_model)
    @asynccontextmanager
    async def lifespan(app):
        # The planner can be deterministic while its approved read actions still go
        # through the authenticated CareLoop MCP connection. This makes the default
        # offline-model demo behave like the configured provider modes.
        await asyncio.to_thread(hub.start)
        app.state.agent=CareLoopVoiceAgent(hub,settings)
        yield
        if hub.started: await asyncio.to_thread(hub.stop)
    app=FastAPI(title="CareLoop local voice simulator",lifespan=lifespan);app.state.settings=settings
    @app.get("/",include_in_schema=False)
    def index(): return FileResponse(FRONTEND/"voice.html")
    @app.get("/api/config")
    def config(): return {"voice":settings.voice,"stt":settings.stt,"llm":settings.llm,"sessions":[{"id":"patient","label":"Patient private session"},{"id":"caregiver","label":"Caregiver private session"}],"mcp":"connected" if hub.started else "starting"}
    @app.get("/api/health")
    def health(): return {"status":"ok","mcp_url":settings.careloop_mcp_url,"voice":settings.voice,"stt":settings.stt}
    @app.post("/api/chat")
    def chat(body:ChatIn):
        # Caregiver transcript is deliberately generic: the UI never receives tool content or record data.
        try: turn=app.state.agent.respond(body.text.strip(),body.session_id)
        except Exception as exc: raise HTTPException(502,"CareLoop MCP connection is unavailable") from exc
        reply=turn.reply if body.persona=="patient" else _generic(turn.reply)
        return {"reply":reply,"tools":turn.tools,"persona":body.persona,"private":True}
    @app.post("/api/chat/stream")
    async def chat_stream(body:ChatIn):
        """Return a small SSE stream so the browser can reveal the response live."""
        async def events():
            try:
                turn=await asyncio.to_thread(app.state.agent.respond,body.text.strip(),body.session_id)
                reply=turn.reply if body.persona=="patient" else _generic(turn.reply)
                yield _sse("message",{"type":"assistant_start","persona":body.persona})
                for tool in turn.tools:
                    yield _sse("message",{"type":"tool","tool":tool})
                # Word-sized fragments look natural without making the mock path slow.
                fragments=reply.split(" ")
                for index, fragment in enumerate(fragments):
                    yield _sse("message",{"type":"assistant_delta","text":fragment + (" " if index < len(fragments)-1 else "")})
                    await asyncio.sleep(0.018)
                yield _sse("message",{"type":"assistant_done","reply":reply,"private":True})
            except Exception:
                yield _sse("message",{"type":"error","message":"The private CareLoop connection is unavailable. Check that the service and simulator are running."})
        return StreamingResponse(events(),media_type="text/event-stream",headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})
    @app.post("/api/tts")
    def tts(body:SpeakIn):
        if voice is None: raise HTTPException(404,"Browser speech synthesis is active")
        try:return Response(voice.synthesize(body.text),media_type=voice.media_type)
        except Exception as exc:raise HTTPException(503,"Local speech output is unavailable") from exc
    @app.post("/api/stt")
    async def stt(request:Request):
        if listener is None: raise HTTPException(404,"Browser speech recognition is active")
        data=await request.body()
        if len(data)>960000:raise HTTPException(413,"Audio is limited to 30 seconds")
        try:return {"text":await asyncio.to_thread(listener.transcribe,data,int(request.headers.get("x-sample-rate","16000")))}
        except Exception as exc:raise HTTPException(503,"Local speech recognition is unavailable") from exc
    app.mount("/static",StaticFiles(directory=FRONTEND),name="static");return app
def _generic(reply:str)->str:
    if "cannot" in reply.lower():return reply
    return "A CareLoop update was handled in your private, consent-scoped session. No private care details are shown here."


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"
