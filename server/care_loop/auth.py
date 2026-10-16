"""CareLoop-specific bearer identities."""
from __future__ import annotations

import hmac
from dataclasses import dataclass
from collections.abc import Mapping

from starlette.types import ASGIApp, Receive, Scope, Send

from .config import Settings

LOCAL_DEMO_TOKEN = "careloop-local-demo-token"
LOCAL_CAREGIVER_TOKEN = "careloop-local-caregiver-token"

def uses_demo_tokens(settings: Settings) -> bool:
    """True when the built-in, publicly documented demo tokens would be accepted."""
    token = settings.api_token or LOCAL_DEMO_TOKEN
    if token == LOCAL_DEMO_TOKEN or settings.caregiver_token == LOCAL_CAREGIVER_TOKEN:
        return True
    return False


class AuthError(PermissionError):
    pass

@dataclass(frozen=True)
class Identity:
    subject_id: str
    role: str = "patient"  # patient or caregiver
    patient_id: str | None = None
    token_id: str | None = None

    @property
    def patient(self) -> str:
        return self.patient_id or self.subject_id

class TokenAuth:
    """Replaceable local-demo identity adapter; production account linking stays outside this adapter."""
    def __init__(self, tokens: Mapping[str, Identity]) -> None:
        self._tokens = dict(tokens)

    @classmethod
    def from_settings(cls, settings: Settings) -> "TokenAuth":
        token = settings.api_token or LOCAL_DEMO_TOKEN
        tokens = {token: Identity(settings.patient_id, "patient", settings.patient_id, "demo")}
        # A synthetic caregiver for the same demo patient. The local default is
        # enabled only alongside the local demo patient token; any custom
        # deployment must set CARELOOP_CAREGIVER_TOKEN explicitly. The
        # caregiver still has no access until the patient's invitation is accepted.
        caregiver = settings.caregiver_token or (LOCAL_CAREGIVER_TOKEN if token == LOCAL_DEMO_TOKEN else None)
        if caregiver and caregiver != token:
            tokens[caregiver] = Identity(settings.caregiver_id, "caregiver", settings.patient_id, "demo-caregiver")
        return cls(tokens)

    def identity_for_token(self, token: str | None) -> Identity | None:
        if not token:
            return None
        for known, identity in self._tokens.items():
            if hmac.compare_digest(known.encode(), token.encode()):
                return identity
        return None

    def identity_for_headers(self, headers: Mapping[str, str] | None) -> Identity:
        raw = (headers or {}).get("authorization") or (headers or {}).get("Authorization") or ""
        scheme, _, token = raw.strip().partition(" ")
        identity = self.identity_for_token(token.strip()) if scheme.lower() == "bearer" else None
        if identity is None:
            raise AuthError("missing or invalid CareLoop bearer token")
        return identity

class BearerAuthMiddleware:
    def __init__(self, app: ASGIApp, auth: TokenAuth, protected_prefix: str = "/mcp") -> None:
        self.app, self.auth, self.protected_prefix = app, auth, protected_prefix
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith(self.protected_prefix):
            await self.app(scope, receive, send); return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        try:
            identity = self.auth.identity_for_headers(headers)
        except AuthError:
            # Alexa+ requires a plain 401 without WWW-Authenticate (not yet supported by its MCP client).
            body = b'{"error":"unauthorized","message":"missing or invalid CareLoop bearer token"}'
            await send({"type":"http.response.start","status":401,"headers":[(b"content-type",b"application/json"),(b"content-length",str(len(body)).encode())]})
            await send({"type":"http.response.body","body":body}); return
        scope.setdefault("state", {})["careloop_identity"] = identity
        await self.app(scope, receive, send)
