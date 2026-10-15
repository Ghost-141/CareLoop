"""Configuration for the local CareLoop voice simulator."""
from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv() -> None:
    """Load simple KEY=VALUE pairs from the standalone project's .env file.

    Environment variables win so deployment tooling can still override a local
    demo configuration.  This deliberately avoids adding a runtime dependency
    just to read a small local configuration file.
    """
    env_file = Path(__file__).resolve().parents[3] / ".env"
    if not env_file.is_file():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)

@dataclass(frozen=True)
class VoiceSimSettings:
    careloop_mcp_url: str = "http://127.0.0.1:8010/mcp"
    careloop_api_url: str = "http://127.0.0.1:8010/api/care"
    api_token: str = "careloop-local-demo-token"
    sim_host: str = "127.0.0.1"
    sim_port: int = 8020
    llm: str = "ollama"
    llm_base_url: str = "http://localhost:11434"
    llm_model: str = ""
    llm_api_key: str = ""
    llm_timeout_seconds: int = 120
    # Ollama treats -1 as no generated-token cap (the model context window is
    # still its natural bound). A spoken answer must not be cut by the app.
    llm_max_tokens: int = -1
    voice: str = "browser"  # browser | kokoro
    stt: str = "browser"  # browser | whisper
    kokoro_voice: str = "af_heart"
    kokoro_speed: float = 1.0
    whisper_model: str = "mlx-community/whisper-small.en-mlx"

    @classmethod
    def from_env(cls) -> "VoiceSimSettings":
        _load_dotenv()
        def value(name: str, default: str) -> str: return os.environ.get(name, default).strip()
        settings = cls(careloop_mcp_url=value("CARELOOP_MCP_URL", cls.careloop_mcp_url),
          careloop_api_url=value("CARELOOP_API_URL", cls.careloop_api_url), api_token=value("CARELOOP_API_TOKEN", cls.api_token),
          sim_host=value("CARELOOP_SIM_HOST", cls.sim_host), sim_port=int(value("CARELOOP_SIM_PORT", str(cls.sim_port))),
          llm=value("CARELOOP_AGENT_LLM", value("AGENT_LLM", "ollama")).lower(),
          llm_base_url=value("LLM_BASE_URL", cls.llm_base_url), llm_model=value("LLM_MODEL", ""),
          llm_api_key=value("LLM_API_KEY", ""), llm_timeout_seconds=int(value("LLM_TIMEOUT_SECONDS", "120")), llm_max_tokens=int(value("LLM_MAX_TOKENS", "-1")), voice=value("VOICE", "browser").lower(), stt=value("STT", "browser").lower(),
          kokoro_voice=value("KOKORO_VOICE", cls.kokoro_voice), kokoro_speed=float(value("KOKORO_SPEED", "1.0")),
          whisper_model=value("WHISPER_MODEL", cls.whisper_model))
        if settings.llm != "ollama": raise ValueError("CARELOOP_AGENT_LLM must be ollama")
        if settings.voice not in {"browser", "kokoro"} or settings.stt not in {"browser", "whisper"}: raise ValueError("VOICE/STT must be browser, kokoro, or whisper")
        if not settings.llm_model: raise ValueError("LLM_MODEL is required for Ollama voice responses")
        return settings
