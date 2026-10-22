# Setup, running and testing

How to install CareLoop, run the Alexa+ demo, and test it. For settings, see [CARELOOP_CONFIGURATION.md](CARELOOP_CONFIGURATION.md); for the screens, see [CARELOOP_UI_GUIDE.md](CARELOOP_UI_GUIDE.md).

## Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/) and Python 3.12+ (uv can install it).
- Chrome, for the microphone and browser speech.
- *Optional:* a model, either any OpenAI-compatible API or [Ollama](https://ollama.com) with a tool-calling model. Without one, a scripted planner answers and documents are read by pattern matching.
- *Optional:* local speech (Kokoro and Whisper) works on any 64-bit Mac, Windows or Linux machine. Without it, the browser's own speech is used.

## Install

```bash
git clone https://github.com/Ghost-141/CareLoop.git
cd CareLoop
uv sync --extra dev --extra alexa-sim --extra voice --extra intake --extra ocr
uv run python evals/intake/documents.py   # writes synthetic sample documents to samples/
uv run pytest -q                          # confirms the install
```

**Optional: a model and local voice.** Copy the example file (`copy` on Windows) and remove the `#` from the lines you need. `.env` is Git-ignored.

```bash
cp .env.example .env
```

- **Hosted model:** `CARELOOP_AGENT_LLM=openai`, plus `LLM_BASE_URL`, `LLM_API_KEY` and a tool-calling `LLM_MODEL`. The text of a shared document is sent to that endpoint.
- **Ollama:** `LLM_MODEL=gemma4:e4b`, then `ollama pull gemma4:e4b`.
- **Local voice:** `VOICE=kokoro` and `STT=whisper`. Models download on first run.

If the model can't be reached, the simulator falls back to the scripted planner by itself.

## Run the Alexa+ demo

```bash
scripts/run_alexa_demo.sh
```

This starts the CareLoop MCP server on `:8010`, then the simulator on `:8021`, and prints the URL to open in Chrome. A busy port is skipped for the next free one. Closing the terminal stops both.

**Demo data.** An empty database is seeded with a starting day: Maya has accepted data use, Sam is in her care circle, pain check-ins of 3, 4 and 7 are logged, and one question is saved for her clinician. Her prescription is *not* loaded; share it from the Alexa app. A check-in of 7 or more today fires her approved rule. **Reset demo data** in Backstage (press twice) restores this day.

| Variant | Command |
| --- | --- |
| Restore the starting day | `scripts/run_alexa_demo.sh --reset` |
| Day four at home: approved plan and three days of history | `scripts/run_alexa_demo.sh --reset --story=history` |
| Start with nothing | `scripts/run_alexa_demo.sh --empty` |
| Same replies every run | `CARELOOP_AGENT_LLM=mock scripts/run_alexa_demo.sh` |
| Browser speech | `VOICE=browser STT=browser scripts/run_alexa_demo.sh` |

**First run with local voice:** Kokoro (about 115 MB) and Whisper (a few hundred MB) download, which takes a few minutes. The top bar shows `Voice: Kokoro · Listening: Whisper` when ready; until then the page uses browser speech.

**No bash?** On Windows use WSL or Git Bash, or run these in two terminals (not tested on Windows):

```powershell
# terminal 1
uv run python scripts/seed_careloop_demo.py
$env:CARELOOP_DEMO_RESET = "true"   # cmd: set CARELOOP_DEMO_RESET=true
uv run careloop

# terminal 2, then open http://127.0.0.1:8021
uv run careloop-alexa-sim
```

## Testing

```bash
uv run pytest -q                       # everything
uv run pytest -q server/tests          # MCP server, tools, consent, views, elicitation
uv run pytest -q alexa_sim/tests       # simulator, including a live run of the whole demo story
uv run python scripts/e2e_careloop_demo.py      # API-level journey; report in .careloop-e2e/
uv run python evals/run_careloop.py --repeat 3  # standalone eval cases with flakiness reporting
```

Any MCP client can connect to `http://127.0.0.1:8010/mcp` (after `uv run careloop`) with `Authorization: Bearer careloop-local-demo-token`.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| "CareLoop account linking failed" | The server isn't running. Use `scripts/run_alexa_demo.sh`, or check `/healthz` |
| Planner shows `mock` although a model is set | The model isn't reachable or `LLM_MODEL` isn't pulled; the inspector logs `planner_fallback` |
| Top bar says `Voice: browser` | Models still downloading, the `voice` extra is missing, or a download failed (`/api/voice` on the simulator shows why) |
| Mic does nothing | Allow microphone access for `127.0.0.1` in Chrome; typing always works |
| Unexpected replies | Use `CARELOOP_AGENT_LLM=mock` and `--reset` |
