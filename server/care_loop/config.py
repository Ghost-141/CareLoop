"""Configuration for the standalone CareLoop MCP server."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv() -> None:
    """Load local CareLoop settings without overriding real environment values."""
    env_file = Path(__file__).resolve().parents[2] / ".env"
    if not env_file.is_file():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            os.environ.setdefault(key, value.strip().strip('"').strip("'"))


LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _csv(raw: str | None) -> tuple[str, ...]:
    return tuple(part.strip() for part in (raw or "").split(",") if part.strip())


def default_llm_model(intake: bool = False) -> str:
    """The Ollama model named in ``.env`` or the environment, else ``gemma4:e4b``.

    Follows the same order as the server: the intake model, when asked for, falls back to ``LLM_MODEL``.
    """
    _load_dotenv()
    named = (os.environ.get("CARELOOP_INTAKE_MODEL") if intake else None) or os.environ.get("LLM_MODEL")
    return (named or "gemma4:e4b").strip()


@dataclass(frozen=True)
class Settings:
    db_path: str = "data/careloop.db"
    api_token: str | None = None
    patient_id: str = "demo-patient"
    host: str = "127.0.0.1"
    port: int = 8010
    retention_days: int = 365
    rate_limit_per_minute: int = 120
    caregiver_token: str | None = None
    caregiver_id: str = "demo-caregiver"
    intake_llm: str = "ollama"  # ollama | openai (any OpenAI-compatible endpoint) | none (pattern matching only)
    intake_model: str = ""
    intake_ocr: str = "paddle"  # paddle | none
    llm_base_url: str = "http://127.0.0.1:11434"  # Ollama address (document reading)
    llm_url: str = ""  # LLM_BASE_URL as given: the OpenAI-compatible endpoint
    llm_api_key: str = ""
    intake_base_url: str = ""  # CARELOOP_INTAKE_BASE_URL: a separate endpoint just for document reading
    timezone: str = ""  # IANA zone for the demo patient's local times; empty = this machine's zone
    patient_name: str = "Maya"  # the synthetic demo patient's spoken name
    require_consent: bool = True  # voice tools ask for data-use consent before first use
    demo_reset: bool = False  # allow POST /api/care/demo/reset to wipe and reseed the demo patient
    suggest_checkin_hour: int = 18  # local hour after which "you haven't checked in today" may be raised
    allow_demo_tokens: bool = False  # permit the built-in demo tokens on a non-loopback host
    allowed_hosts: tuple[str, ...] = ()  # extra Host header values accepted on /mcp (e.g. a tunnel hostname)
    allowed_origins: tuple[str, ...] = ()  # extra browser Origin values accepted on /mcp

    @property
    def is_loopback(self) -> bool:
        return self.host.strip().lower() in LOOPBACK_HOSTS

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        if env is None:
            _load_dotenv()
        source = os.environ if env is None else env
        def value(name: str, default: str) -> str:
            return (source.get(name, default) or default).strip()
        try:
            return cls(
                db_path=value("CARELOOP_DB_PATH", "data/careloop.db"),
                api_token=source.get("CARELOOP_API_TOKEN") or None,
                patient_id=value("CARELOOP_DEMO_PATIENT", "demo-patient"),
                host=value("CARELOOP_HOST", "127.0.0.1"),
                port=int(value("CARELOOP_PORT", "8010")),
                retention_days=int(value("CARELOOP_RETENTION_DAYS", "365")),
                rate_limit_per_minute=int(value("CARELOOP_RATE_LIMIT_PER_MINUTE", "120")),
                caregiver_token=source.get("CARELOOP_CAREGIVER_TOKEN") or None,
                caregiver_id=value("CARELOOP_DEMO_CAREGIVER", "demo-caregiver"),
                # Document reading follows the voice planner's provider unless told otherwise.
                intake_llm=value("CARELOOP_INTAKE_LLM", "openai" if value("CARELOOP_AGENT_LLM", "").lower() == "openai" else "ollama").lower(),
                intake_model=(source.get("CARELOOP_INTAKE_MODEL") or source.get("LLM_MODEL") or "").strip(),
                intake_ocr=value("CARELOOP_INTAKE_OCR", "paddle").lower(),
                # Document reading talks to Ollama. LLM_BASE_URL is the shared setting, except when the voice
                # planner uses an OpenAI-compatible endpoint, which isn't an Ollama address.
                llm_base_url=(source.get("CARELOOP_INTAKE_BASE_URL")
                              or ("" if value("CARELOOP_AGENT_LLM", "").lower() == "openai" else source.get("LLM_BASE_URL"))
                              or "http://127.0.0.1:11434").strip(),
                llm_url=(source.get("LLM_BASE_URL") or "").strip(),
                llm_api_key=(source.get("LLM_API_KEY") or "").strip(),
                intake_base_url=(source.get("CARELOOP_INTAKE_BASE_URL") or "").strip(),
                timezone=(source.get("CARELOOP_TIMEZONE") or "").strip(),
                patient_name=value("CARELOOP_DEMO_PATIENT_NAME", "Maya"),
                require_consent=value("CARELOOP_REQUIRE_CONSENT", "true").lower() not in {"0", "false", "no", "off"},
                demo_reset=value("CARELOOP_DEMO_RESET", "false").lower() in {"1", "true", "yes", "on"},
                suggest_checkin_hour=min(23, max(0, int(value("CARELOOP_SUGGEST_CHECKIN_HOUR", "18")))),
                allow_demo_tokens=value("CARELOOP_ALLOW_DEMO_TOKENS", "false").lower() in {"1", "true", "yes", "on"},
                allowed_hosts=_csv(source.get("CARELOOP_ALLOWED_HOSTS")),
                allowed_origins=_csv(source.get("CARELOOP_ALLOWED_ORIGINS")),
            )
        except ValueError as exc:
            raise ValueError("CareLoop port, retention, and rate limit must be integers") from exc
