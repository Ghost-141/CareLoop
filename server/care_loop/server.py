"""Standalone CareLoop MCP endpoint at ``/mcp``."""
from __future__ import annotations
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from mcp.server.mcpserver import MCPServer, Context
from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp
from . import __version__
from .auth import AuthError, BearerAuthMiddleware, Identity, TokenAuth
from .config import Settings
from .core import AccessDenied, CareLoopService
from .storage import CareLoopStorage
from .tools import records
from . import ui
from .portal import build_router

SERVER_NAME="careloop"; MAX_REQUEST_BYTES=64*1024
INSTRUCTIONS=(
    "CareLoop is an isolated synthetic adult-patient demo. Use only authenticated CareLoop records. "
    "Every tool result has status, speakable, surface, view, and refs fields. Alexa+ must speak only the "
    "speakable field. Tool results never contain private care data; refs are opaque ids with positional "
    "labels (for example 'draft task 1') to pass back to action tools. Confirm with the user before "
    "destructive tools. Render the tool's ui://careloop view only in an authenticated private MCP App; "
    "never quote, summarize, or expose get_private_view data or that view on a shared voice surface. "
    "Do not diagnose, change treatment, or claim emergency monitoring. "
    "Care content is private."
)

@dataclass
class Deps:
    settings: Settings
    storage: CareLoopStorage
    auth: TokenAuth
    service: CareLoopService
    local_identity: Identity | None = None
    def identity(self, ctx: Context) -> Identity:
        if ctx.headers is None and self.local_identity: return self.local_identity
        try: return self.auth.identity_for_headers(ctx.headers)
        except AuthError as exc: raise AccessDenied() from exc

def build_deps(settings: Settings | None=None, **overrides: Any) -> Deps:
    settings=settings or Settings.from_env()
    storage=overrides.get("storage") or CareLoopStorage(settings.db_path)
    auth=overrides.get("auth") or TokenAuth.from_settings(settings)
    service=overrides.get("service") or CareLoopService(storage,overrides.get("clock") or storage.clock,
                                                         settings.retention_days)
    return Deps(settings,storage,auth,service,overrides.get("local_identity"))

def build_server(deps: Deps) -> MCPServer:
    mcp=MCPServer(name=SERVER_NAME,title="CareLoop",version=__version__,instructions=INSTRUCTIONS)
    records.register(mcp,deps)
    ui.register(mcp,deps)
    @mcp.custom_route("/healthz",methods=["GET"])
    async def healthz(request: Request) -> JSONResponse:
        return JSONResponse({"status":"ok","version":__version__,"service":"careloop"})
    return mcp

def create_app(deps: Deps | None=None) -> ASGIApp:
    deps=deps or build_deps(); mcp=build_server(deps)
    mcp_app=mcp.streamable_http_app(streamable_http_path="/mcp",host=deps.settings.host,max_request_body_size=MAX_REQUEST_BYTES)
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # Mounted ASGI applications do not receive lifespan events by default.
        # MCP needs this to initialize its Streamable HTTP session task group.
        async with mcp_app.router.lifespan_context(mcp_app):
            yield
    app = FastAPI(title="CareLoop private portal", lifespan=lifespan)
    app.include_router(build_router(deps.service, deps.auth))
    # The MCP sub-application remains separate from portal routes; the parent
    # middleware accepts only CareLoop bearer identities for its /mcp prefix.
    app.mount("/", mcp_app)
    return BearerAuthMiddleware(app,deps.auth)

def main() -> None:
    import uvicorn
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings=Settings.from_env()
    uvicorn.run(create_app(build_deps(settings)),host=settings.host,port=settings.port,log_level="info")

if __name__ == "__main__": main()
