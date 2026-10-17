from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv() -> None:
    """Load the project ``.env`` without overriding real environment values."""
    env_file = Path(__file__).resolve().parents[3] / ".env"
    if not env_file.is_file():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class AlexaSimSettings:
    mcp_url: str = "http://127.0.0.1:8010/mcp"
    api_url: str = ""  # CareLoop REST base for document uploads; defaults to the MCP server's origin
    host: str = "127.0.0.1"
    port: int = 8021
    max_tool_steps: int = 4
    # Account linking is simulated with server-held synthetic credentials.
    # They never reach the browser.
    patient_token: str = "careloop-local-demo-token"
    caregiver_token: str = "careloop-local-caregiver-token"
    planner: str = "mock"  # mock | ollama | openai (any OpenAI-compatible endpoint)
    llm_base_url: str = "http://127.0.0.1:11434"
    llm_model: str = ""
    llm_api_key: str = ""
    llm_timeout_seconds: float = 60.0
    voice: str = "browser"  # browser | kokoro
    stt: str = "browser"  # browser | whisper
    kokoro_voice: str = "af_heart"
    kokoro_speed: float = 1.0
    whisper_model: str = "small.en"  # a size name works on every engine; an MLX repo id also works
    voice_models_dir: Path | None = None
    idle_reset_minutes: float = 0  # shared demo: wipe and reseed after this long without use (0 = never)

    @classmethod
    def from_env(cls) -> "AlexaSimSettings":
        _load_dotenv()
        env = os.environ
        # Setting LLM_MODEL is enough to use Ollama; CARELOOP_AGENT_LLM=mock still forces the scripted planner.
        planner = (env.get("CARELOOP_AGENT_LLM") or ("ollama" if env.get("LLM_MODEL", "").strip() else cls.planner)).strip().lower()
        return cls(
            mcp_url=env.get("CARELOOP_MCP_URL", cls.mcp_url),
            api_url=env.get("CARELOOP_SERVER_URL", ""),
            host=env.get("CARELOOP_ALEXA_SIM_HOST", cls.host),
            port=int(env.get("CARELOOP_ALEXA_SIM_PORT", str(cls.port))),
            max_tool_steps=max(1, int(env.get("CARELOOP_ALEXA_SIM_MAX_TOOL_STEPS", "4"))),
            patient_token=env.get("CARELOOP_API_TOKEN") or cls.patient_token,
            caregiver_token=env.get("CARELOOP_CAREGIVER_TOKEN") or cls.caregiver_token,
            planner=planner if planner in {"mock", "ollama", "openai"} else "mock",
            llm_base_url=env.get("LLM_BASE_URL", cls.llm_base_url),
            llm_model=env.get("LLM_MODEL", ""),
            llm_api_key=env.get("LLM_API_KEY", ""),
            llm_timeout_seconds=float(env.get("LLM_TIMEOUT_SECONDS", "60") or 60),
            voice="kokoro" if env.get("VOICE", "").strip().lower() == "kokoro" else "browser",
            stt="whisper" if env.get("STT", "").strip().lower() == "whisper" else "browser",
            kokoro_voice=env.get("KOKORO_VOICE", cls.kokoro_voice) or cls.kokoro_voice,
            kokoro_speed=float(env.get("KOKORO_SPEED", "1.0") or 1.0),
            whisper_model=env.get("WHISPER_MODEL", cls.whisper_model) or cls.whisper_model,
            voice_models_dir=Path(env["CARELOOP_VOICE_MODELS_DIR"]).expanduser() if env.get("CARELOOP_VOICE_MODELS_DIR") else None,
            idle_reset_minutes=max(0.0, float(env.get("CARELOOP_DEMO_IDLE_RESET_MINUTES", "0") or 0)),
        )

    @property
    def server_url(self) -> str:
        return (self.api_url or self.mcp_url.rsplit("/mcp", 1)[0]).rstrip("/")

    def token_for(self, account: str) -> str:
        return self.patient_token if account == "maya" else self.caregiver_token
