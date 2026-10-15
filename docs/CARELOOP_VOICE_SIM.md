# Local CareLoop voice simulator

This is a local Alexa+-style browser simulation, not an Alexa+ account connection, certification, or production voice feature. It uses Ollama for every normal spoken response. CareLoop authorizes actions and supplies only safe tool-result facts; Ollama turns those approved facts into natural speech.

## Run

In one terminal start CareLoop:

```bash
uv run careloop
```

In another terminal:

```bash
uv sync --extra simulator --extra voice
cp .env.example .env
scripts/run_careloop_voice_demo.sh
```

Open `http://127.0.0.1:8020`. The page has an audio-first voice control, live speech transcript, streaming assistant reply, a spoken answer, separate patient/caregiver private sessions, typed fallback, and planned demo prompts. The picker is a demo control; it does not prove identity.

## Configuration

CareLoop loads `.env` automatically for both the core service and the voice simulator. Copy `.env.example` once, then change only the values you need. `.env` is ignored by Git; never commit an API key.

```dotenv
# Ollama is required for spoken responses
CARELOOP_AGENT_LLM=ollama
LLM_MODEL=qwen3.5:4b-mlx
VOICE=browser
STT=browser

# Optional local model and local speech stack
# CARELOOP_AGENT_LLM=ollama
# LLM_MODEL=qwen3.5:4b-mlx
# LLM_TIMEOUT_SECONDS=120
# LLM_MAX_TOKENS=24
# VOICE=kokoro
# STT=whisper
```

`LLM_API_KEY` is only needed for an intentionally configured hosted-model provider. The browser never receives it or `CARELOOP_API_TOKEN`.

## Modes

```bash
# local Ollama model; actions remain authorization-checked
CARELOOP_AGENT_LLM=ollama LLM_MODEL=qwen3.5:4b-mlx scripts/run_careloop_voice_demo.sh

# local speech output and recognition (Apple Silicon for Whisper)
VOICE=kokoro STT=whisper scripts/run_careloop_voice_demo.sh
```

`CARELOOP_MCP_URL` defaults to `http://127.0.0.1:8010/mcp`; `CARELOOP_API_TOKEN` is retained by the simulator backend and never exposed to browser JavaScript. The configured Ollama model both interprets flexible phrasing and writes the final natural-language response from approved facts. It cannot choose arbitrary tools, provide medical advice, or bypass consent. Kokoro and Whisper are optional. If either is unavailable, the page falls back to browser speech or typed chat. Browser voice recognition availability varies by browser; the text field is always available.

## Privacy boundary

The caregiver view receives generic assistant status and tool chips only. It never renders private plan content, observations, alert details, tokens, or tool results. CareLoop remains the authorization authority; a UI selector cannot grant access.

## Alexa+ behavior simulator

The separate Alexa+ behavior simulator is the judge-facing two-device demo described in [CARELOOP_ALEXA_SIM_DEMO_PLAN.md](CARELOOP_ALEXA_SIM_DEMO_PLAN.md). It is explicitly labelled as a hackathon simulation, not an Amazon product. Unlike the legacy local voice simulator, it discovers tools from `tools/list`, holds one initialized Streamable HTTP MCP session per linked account, records an inspector trace, and renders a CareLoop MCP App only inside a sandboxed iframe.

```bash
# Terminal 1 (or let the helper launch it)
uv run careloop

# Terminal 2
uv run careloop-alexa-sim
# or: scripts/run_alexa_demo.sh
```

Open `http://127.0.0.1:8021`, link Maya and Sam through the demo Alexa-app panel, then use typed input as the reliable stage fallback. The current mock-replay fallback covers task and generic-notification prompts while dynamically discovered MCP tools remain visible in the Inspector. Browser speech synthesis is used when available; no Amazon branding or voice is used.
