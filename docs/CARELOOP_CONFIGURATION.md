# Configuration

Settings come from environment variables. Everything has a default, and a `.env` file is optional (see `.env.example`). It is loaded automatically, and shell variables take precedence.

| Variable | Default | Purpose |
| --- | --- | --- |
| `CARELOOP_HOST` / `CARELOOP_PORT` | `127.0.0.1` / `8010` | CareLoop server bind address |
| `CARELOOP_ALLOW_DEMO_TOKENS` | `false` | The server refuses to start on a non-loopback host while the built-in demo tokens are active. Set `true` only for a deliberate local-network demo |
| `CARELOOP_ALLOWED_HOSTS` | — | Comma-separated extra `Host` values accepted on `/mcp`, e.g. a tunnel hostname (`demo.example.com`, no port for HTTPS). Loopback is always allowed |
| `CARELOOP_ALLOWED_ORIGINS` | — | Comma-separated extra browser `Origin` values accepted on `/mcp` (loopback origins always allowed) |
| `CARELOOP_DB_PATH` | `data/careloop.db` | SQLite/WAL database |
| `CARELOOP_API_TOKEN` | `careloop-local-demo-token` | Synthetic patient bearer token |
| `CARELOOP_DEMO_PATIENT` | `demo-patient` | Patient identity for that token |
| `CARELOOP_CAREGIVER_TOKEN` | `careloop-local-caregiver-token`* | Synthetic caregiver token (*default only with the local patient token) |
| `CARELOOP_DEMO_CAREGIVER` | `demo-caregiver` | Caregiver identity for that token |
| `CARELOOP_RETENTION_DAYS` | `365` | Retention for non-patient records |
| `CARELOOP_MCP_URL` | `http://127.0.0.1:8010/mcp` | Where the simulators connect |
| `CARELOOP_ALEXA_SIM_PORT` | `8021` | Alexa+ behavior simulator port |
| `CARELOOP_AGENT_LLM` | `ollama` if `LLM_MODEL` is set, else `mock` | Voice planner: `mock`, `ollama`, or `openai` (any OpenAI-compatible endpoint) |
| `LLM_BASE_URL` / `LLM_MODEL` | `http://127.0.0.1:11434` / — | Planner endpoint and tool-calling model. For `openai`, a base like `https://host/v1` or the full `.../v1/chat/completions` URL |
| `LLM_API_KEY` | — | Bearer key for the `openai` planner |
| `CARELOOP_INTAKE_BASE_URL` | `LLM_BASE_URL` | A separate endpoint just for document reading (Ollama's address, or an OpenAI-compatible URL) |
| `VOICE` / `STT` | `browser` | `kokoro` / `whisper` for local speech |
| `KOKORO_VOICE` / `KOKORO_SPEED` | `af_heart` / `1.0` | Kokoro voice settings |
| `WHISPER_MODEL` | `small.en` | Whisper model. A size name (`tiny.en`, `base.en`, `small.en`, …) works on every system. An MLX repo id such as `mlx-community/whisper-small.en-mlx` also works and is translated for faster-whisper |
| `WHISPER_BACKEND` | automatic | Force the engine: `mlx` or `faster`. By default Apple Silicon uses MLX Whisper and everything else uses faster-whisper |
| `CARELOOP_VOICE_MODELS_DIR` | `~/.cache/careloop/voice` | Kokoro model cache |
| `CARELOOP_REQUIRE_CONSENT` | `true` | Ask patients to accept data use before voice tools store or read anything |
| `CARELOOP_DEMO_PATIENT_NAME` | `Maya` | The demo patient's spoken name until they set their own |
| `CARELOOP_DEMO_RESET` | `false` (`run_alexa_demo.sh`: `true`) | Enables `POST /api/care/demo/reset`, which wipes and reseeds the demo patient. Keep off anywhere real |
| `CARELOOP_DEMO_STORY` | `first-visit` | Which starting day seeding and **Reset demo data** use: `first-visit` (the prescription is not loaded yet) or `history` (day four at home). `run_alexa_demo.sh --story=history` sets it |
| `CARELOOP_DEMO_IDLE_RESET_MINUTES` | `0` (off) | The simulator restores the seeded demo after this many minutes without use |
| `CARELOOP_TIMEZONE` | this machine's zone | IANA zone for task times, reminders and missed-task checks (a patient's own setting wins) |
| `CARELOOP_INTAKE_LLM` | follows `CARELOOP_AGENT_LLM` (`openai` or `ollama`) | Document reading provider: `ollama`, `openai`, or `none` for pattern matching only. **With `openai`, the text extracted from a shared document is sent to that endpoint**; the privacy policy says so |
| `CARELOOP_INTAKE_MODEL` | `LLM_MODEL` | Model that structures uploaded documents |
| `CARELOOP_INTAKE_OCR` | `paddle` | OCR for scanned pages and photos (`none` sends them to manual review) |
