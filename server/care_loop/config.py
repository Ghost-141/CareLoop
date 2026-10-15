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
            )
        except ValueError as exc:
            raise ValueError("CareLoop port, retention, and rate limit must be integers") from exc
