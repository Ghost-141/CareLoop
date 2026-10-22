# Configuration

CareLoop runs with no settings. A `.env` file is optional (copy `.env.example`); it is loaded automatically, and shell variables take precedence. Leave a setting out rather than setting it empty.

## Settings you're likely to set

These are the only ones in `.env.example`.

| Variable | Default | Purpose |
| --- | --- | --- |
| `CARELOOP_AGENT_LLM` | `ollama` if `LLM_MODEL` is set, else `mock` | Model standing in for Alexa+'s: `mock` (scripted), `ollama`, or `openai` (any OpenAI-compatible endpoint with tool calling). Document reading follows it |
| `LLM_BASE_URL` | `http://127.0.0.1:11434` | For `openai`, a base like `https://host/v1` or the full `.../v1/chat/completions` URL |
| `LLM_MODEL` | — | A tool-calling model |
| `LLM_API_KEY` | — | Bearer key for `openai` |
| `LLM_TIMEOUT_SECONDS` | `60` | How long to wait for a model reply |
| `VOICE` / `STT` | `browser` | `kokoro` / `whisper` for local speech (models download on first use) |
| `WHISPER_MODEL` | `small.en` | A size name (`tiny.en`, `base.en`, `small.en`, …), or an MLX repo id such as `mlx-community/whisper-small.en-mlx` |

**With `openai`, the text extracted from a shared document is sent to that endpoint.** To keep documents local, set `CARELOOP_INTAKE_LLM=ollama`.

## Everything else

The defaults work for the demo. `scripts/run_alexa_demo.sh` sets the ports and MCP URL itself.

| Variable | Default | Purpose |
| --- | --- | --- |
| **Server** | | |
| `CARELOOP_HOST` / `CARELOOP_PORT` | `127.0.0.1` / `8010` | Bind address |
| `CARELOOP_DB_PATH` | `data/careloop.db` | SQLite/WAL database |
| `CARELOOP_API_TOKEN` | `careloop-local-demo-token` | Synthetic patient bearer token |
| `CARELOOP_DEMO_PATIENT` | `demo-patient` | Patient identity for that token |
| `CARELOOP_CAREGIVER_TOKEN` | `careloop-local-caregiver-token`* | Synthetic caregiver token (*default only with the local patient token) |
| `CARELOOP_DEMO_CAREGIVER` | `demo-caregiver` | Caregiver identity for that token |
| `CARELOOP_ALLOW_DEMO_TOKENS` | `false` | The server refuses to start on a non-loopback host with the demo tokens. Set `true` only for a deliberate local-network demo |
| `CARELOOP_ALLOWED_HOSTS` / `CARELOOP_ALLOWED_ORIGINS` | — | Comma-separated extra `Host` / `Origin` values accepted on `/mcp`, e.g. a tunnel hostname. Loopback is always allowed |
| `CARELOOP_RETENTION_DAYS` | `365` | Retention for non-patient records |
| `CARELOOP_REQUIRE_CONSENT` | `true` | Ask patients to accept data use before voice tools store or read anything |
| `CARELOOP_TIMEZONE` | this machine's zone | IANA zone for task times and reminders (a patient's own setting wins) |
| `CARELOOP_SUGGEST_CHECKIN_HOUR` | `18` | Local hour after which a missing check-in may be suggested |
| **Document reading** | | |
| `CARELOOP_INTAKE_LLM` | `openai` if the planner is `openai`, else `ollama` | `ollama`, `openai`, or `none` for pattern matching only |
| `CARELOOP_INTAKE_MODEL` | `LLM_MODEL` | Model that structures documents |
| `CARELOOP_INTAKE_BASE_URL` | Ollama's address | A separate endpoint just for document reading |
| `CARELOOP_INTAKE_OCR` | `paddle` | OCR for scans and photos (`none` sends them to manual review) |
| **Simulator** | | |
| `CARELOOP_ALEXA_SIM_HOST` / `CARELOOP_ALEXA_SIM_PORT` | `127.0.0.1` / `8021` | Bind address |
| `CARELOOP_MCP_URL` | `http://127.0.0.1:8010/mcp` | The server's MCP endpoint |
| `CARELOOP_SERVER_URL` | the MCP URL's origin | CareLoop REST base for document uploads |
| `CARELOOP_ALEXA_SIM_MAX_TOOL_STEPS` | `4` | Tool calls allowed per request |
| `KOKORO_VOICE` / `KOKORO_SPEED` | `af_heart` / `1.0` | Kokoro voice settings |
| `WHISPER_BACKEND` | automatic | `mlx` or `faster`. Apple Silicon uses MLX Whisper by default |
| `CARELOOP_VOICE_MODELS_DIR` | `~/.cache/careloop/voice` | Kokoro model cache |
| **Demo** | | |
| `CARELOOP_DEMO_PATIENT_NAME` | `Maya` | The patient's spoken name until they set their own |
| `CARELOOP_DEMO_RESET` | `false` (`true` in `run_alexa_demo.sh`) | Enables `POST /api/care/demo/reset`. Keep off anywhere real |
| `CARELOOP_DEMO_STORY` | `first-visit` | Starting day for seeding and **Reset demo data**: `first-visit` or `history` (`--story=history`) |
| `CARELOOP_DEMO_IDLE_RESET_MINUTES` | `0` (off) | Restore the seeded demo after this many idle minutes |
