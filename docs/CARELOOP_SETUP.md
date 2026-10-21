# Setup, running and testing

Everything needed to install CareLoop, run the Alexa+ demo, and test it. For settings, see [CARELOOP_CONFIGURATION.md](CARELOOP_CONFIGURATION.md).

## Prerequisites

| Requirement | Needed for | Check |
| --- | --- | --- |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | Everything | `uv --version` |
| Python 3.12+ (uv can install it) | Everything | `uv python list` |
| A model *(optional)*: any OpenAI-compatible API, or [Ollama](https://ollama.com) with a tool-calling model | Voice planner and document reading | — |
| Any 64-bit Mac, Windows or Linux machine *(optional)* | Local speech: Kokoro and Whisper. Apple Silicon uses MLX Whisper, everything else uses faster-whisper (CPU, or an NVIDIA GPU if present). Models download on first use. | `uv run python -c "import platform; print(platform.machine())"` |
| Chrome *(recommended)* | Microphone input and browser speech fallback | — |

Without a model, the simulator uses its deterministic mock planner. If local speech is not installed or fails to load, the simulator uses the browser's own speech (`STT=browser`).

## Install, step by step

**1. Clone the repository:**

```bash
git clone https://github.com/Ghost-141/CareLoop.git
cd CareLoop
```

**2. Install dependencies.** `dev` adds tests, `alexa-sim` adds WebSocket support, and `voice` adds Kokoro and Whisper:

```bash
uv sync --extra dev --extra alexa-sim --extra voice --extra intake --extra ocr
uv run python evals/intake/documents.py   # writes synthetic sample documents to samples/
```

**3. (Optional) Choose a model and voice.** The demo runs with no settings at all, using a scripted planner, pattern matching for documents, and your browser's own speech. To use a model, copy the example file and edit it:

```bash
cp .env.example .env        # Windows: copy .env.example .env
```

`.env` is Git-ignored. Pick one of two routes:

- **A hosted model.** Any OpenAI-compatible endpoint with tool calling. It drives the voice planner and reads documents, so the text of a shared document is sent to that endpoint:

  ```text
  CARELOOP_AGENT_LLM=openai
  LLM_BASE_URL=https://api.openai.com/v1
  LLM_API_KEY=...
  LLM_MODEL=gpt-4.1-mini
  ```

- **A local model with Ollama.** Set `LLM_MODEL=gemma4:e4b`, then pull it:

  ```bash
  ollama pull gemma4:e4b     # voice planner and document reading
  ```

For local voice, also remove the `#` from `VOICE=kokoro` and `STT=whisper`. The first run downloads the voice models, and the simulator picks the right Whisper engine for your system. Every other setting has a default (see [CARELOOP_CONFIGURATION.md](CARELOOP_CONFIGURATION.md)).

**4. Without a model** the demo uses the scripted planner, and documents are read by pattern matching, so each item needs your review. If the model can't be reached, the simulator falls back to the scripted planner by itself.

**5. Run the tests** to confirm the install:

```bash
uv run pytest -q
# 410 passed
```

## Run the Alexa+ demo

```bash
scripts/run_alexa_demo.sh
```

This starts the CareLoop MCP server on `:8010`, waits until it is healthy, then starts the simulator on `:8021`. Open **http://127.0.0.1:8021** in Chrome. If either port is already taken (by another app or an old run), the script uses the next free port and prints the URL to open.

**Demo data.** If the demo patient has no records, the script seeds a synthetic starting day:
- Maya has accepted data use.
- Sam is in her care circle.
- Pain check-ins of 3, 4 and 7 are logged for the last three days.
- One question is saved for her clinician.

Her prescription is *not* loaded: share it from the Alexa app panel. Because yesterday was a 7, a check-in of 7 or more today fires her approved rule. In Backstage, **Reset demo data** (click twice) restores this starting day at any time, with both devices linked.

| Variant | Command |
| --- | --- |
| Deterministic planner (stage-safe, the same replies every run) | `CARELOOP_AGENT_LLM=mock scripts/run_alexa_demo.sh` |
| Browser speech instead of Kokoro/Whisper | `VOICE=browser STT=browser scripts/run_alexa_demo.sh` |
| Restore the seeded starting day | `scripts/run_alexa_demo.sh --reset` |
| Day four at home: an approved plan with three days of history (suggestions, teach-back, handoff) | `scripts/run_alexa_demo.sh --reset --story=history` |
| Start with nothing: no consent, no care circle, no records | `scripts/run_alexa_demo.sh --empty` |
| Separate demo database | `CARELOOP_DB_PATH=/tmp/careloop-demo.db scripts/run_alexa_demo.sh` |
| Shared machine: restore the demo after 15 idle minutes | `CARELOOP_DEMO_IDLE_RESET_MINUTES=15 scripts/run_alexa_demo.sh` |

**First run:** Kokoro downloads its model (about 115 MB) to `~/.cache/careloop/voice`, and Whisper downloads its model (`small.en` is a few hundred MB) to the Hugging Face cache. This takes a few minutes. The top bar shows `Voice: Kokoro · Listening: Whisper` once both engines are ready; until then the page uses browser speech.

**No bash?** `scripts/run_alexa_demo.sh` needs bash (macOS and Linux have it; on Windows use WSL or Git Bash). Without bash, open two terminals in the repository folder and run these (not tested on Windows):

```powershell
# terminal 1: seed the demo day, then start the server
uv run python scripts/seed_careloop_demo.py
$env:CARELOOP_DEMO_RESET = "true"   # cmd: set CARELOOP_DEMO_RESET=true
uv run careloop

# terminal 2: start the simulator, then open http://127.0.0.1:8021
uv run careloop-alexa-sim
```

## Using the simulator

- **Devices:** *Maya's Echo Show* (patient, with a screen) and *Sam's Echo Dot* (caregiver, voice only).
- **Talk:** tap the 🎤 on a device and speak, or tick **Hands-free "Alexa…"** and pick which device hears you. Saying "stop" interrupts speech. Typing in a device's box, or tapping a prompt chip, does the same as speaking.
- **Alexa app panel:** **Enable CareLoop** links an account (synthetic credentials stay on the server). **Sam opens Maya's invitation link** simulates Sam accepting her invite.
- **Backstage panel:** switch the stand-in planner (OpenAI-compatible API ↔ Ollama ↔ mock), reset the conversation, ring the next simulated reminder, and **Reset demo data** (wipes only the demo patient and reseeds the starting day).
- **MCP inspector:** every `tools/list`, `tools/call`, `resources/read` and `elicitation/create` message, live.

## Testing

```bash
uv run pytest -q                       # all 410 tests
uv run pytest -q server/tests          # MCP server, tools, consent, MCP Apps views, elicitation
uv run pytest -q alexa_sim/tests       # simulator host and scripted evaluator, incl. a live run of the demo story
```

The `alexa_sim` live test (`test_full_demo_story_against_live_careloop`) starts a real CareLoop server process with a temporary database and drives the whole demo story through the simulator API: linking, approval, invite and accept, the elicitation check-in, caregiver privacy, acknowledgement, handoff, and confirmed revocation.

Other checks:

```bash
uv run python scripts/e2e_careloop_demo.py      # API-level synthetic journey; sanitized report in .careloop-e2e/
uv run python evals/run_careloop.py --repeat 3  # 16 standalone eval cases with flakiness reporting
```

To inspect the MCP server with any standard MCP client, run `uv run careloop` and connect to `http://127.0.0.1:8010/mcp` with header `Authorization: Bearer careloop-local-demo-token`.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| "CareLoop account linking failed" | The server isn't running on `:8010`. Use `scripts/run_alexa_demo.sh`, or check `curl http://127.0.0.1:8010/healthz` |
| Port already in use | Stop the other process, or set `CARELOOP_PORT` / `CARELOOP_ALEXA_SIM_PORT` (and `CARELOOP_MCP_URL`) |
| Planner shows `mock` although Ollama is set | Ollama isn't reachable or `LLM_MODEL` isn't pulled. The host falls back to mock per turn; the inspector logs `planner_fallback` |
| Top bar says `Voice: browser` | Kokoro/Whisper still loading (first run downloads models), the `voice` extra is missing (`uv sync --extra voice`), or a model download failed. The page keeps working with browser speech. `/api/voice` on the simulator lists the error |
| Mic does nothing | Allow microphone access for `127.0.0.1` in Chrome; typed input always works |
| Replies differ from the walkthrough | Use `CARELOOP_AGENT_LLM=mock` and a fresh `CARELOOP_DB_PATH` |
| Inspector not updating live | Install the `alexa-sim` extra (WebSockets); the page also polls every 4 s |
