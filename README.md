# CareLoop

**CareLoop turns a clinician-provided plan into a patient-controlled, accountable care loop, built as an MCP add-on for Alexa+.** A patient approves a cited plan, records check-ins, shares narrowly scoped access with a caregiver, gets deterministic rule-driven updates, and produces a factual visit handoff. Every step is an auditable MCP tool call.

> Built for the **Amazon Developer Hackathon 2026 ("Build, Ship, Shape"), Alexa+ track.** It includes an Alexa+ *behavior simulator* web app (`alexa_sim/`), which is **not an Amazon product**. All data is synthetic.

**Product page:** [ghost-141.github.io/CareLoop](https://ghost-141.github.io/CareLoop/) (source in `site/`, published by `.github/workflows/pages.yml`).

CareLoop is intentionally bounded. It does **not** diagnose, prescribe, adjust medication, interpret missing data as normal, promise emergency monitoring, or use real patient data.

| | |
| --- | --- |
| Protocol | MCP 2025-11-25 over Streamable HTTP at `/mcp`; MCP Apps views (`ui://careloop/*`); MCP elicitation. Discovery, tool listing and tool calls also work under 2026-07-28; elicitation tools do not yet ([friction log F-28](docs/FRICTION_LOG.md)) |
| Server | Python, FastAPI, official MCP Python SDK, SQLite/WAL |
| Assistant simulator | Echo Show-style and Echo Dot-style devices, simulated Alexa app account linking, live MCP inspector |
| Voice | Local Kokoro TTS and Whisper STT on any system (MLX Whisper on Apple Silicon, faster-whisper on Windows, Linux and Intel Macs), with browser speech fallback |
| Planner | In production, Alexa+'s own model chooses the tools. The simulator stands in with any OpenAI-compatible API, a local Ollama model, or a deterministic mock for stage safety |
| Identity | Credential-derived patient/caregiver identities; no caller-supplied patient scope |
| Privacy | Voice-safe tool results, patient-owned expiring grants, generic caregiver notifications, deletion and purge |
| Document intake | Prescription/plan upload: PDF text first, PaddleOCR fallback, local LLM proposes items, deterministic checks, patient approves each item |
| Tests | 410 tests, including live end-to-end runs against a real server; an intake eval against the configured model |

## Contents

1. [What CareLoop adds to Alexa+](#what-careloop-adds-to-alexa)
2. [Prerequisites](#prerequisites)
3. [Setup, step by step](#setup-step-by-step)
4. [Run the Alexa+ demo](#run-the-alexa-demo)
5. [Demo walkthrough](#demo-walkthrough)
6. [Testing](#testing)
7. [MCP surface](#mcp-surface)
8. [Architecture](#architecture)
9. [Configuration](#configuration)
10. [Troubleshooting](#troubleshooting)
11. [Repository layout](#repository-layout)
12. [Safety and privacy boundaries](#safety-and-privacy-boundaries)
13. [License](#license)

## What CareLoop adds to Alexa+

Alexa+ can remember documents, set reminders, and alert family about activity. CareLoop adds what those features don't do: an **accountable record** of who approved what, who can see what, what a rule decided, and what the clinician receives.

| Capability | What CareLoop does |
| --- | --- |
| Approval with citations | A plan becomes **drafts with source citations**; nothing is active until the patient approves each item |
| A source for every claim | Every card on the patient's screen says where it came from: the document line, or the record it was worked out from. A triggered alert shows its rule's line and the check-ins that fired it |
| Teach-back | "Check I understood my plan": CareLoop asks the patient to say back when or how often they take each medicine, the alert rule's numbers and a warning sign's number, and checks every answer in code. A miss is answered by reading the plan back in its own words, never by explaining. Results go to the visit handoff |
| Follow-up questions | `start_daily_checkin` asks its own question through **MCP elicitation**, validates the answer (0–10), and re-asks if needed |
| Deterministic rules | Only a patient-approved, source-backed rule can create an alert, at most once per episode |
| Privacy on shared speakers | Tool results expose only a `speakable` line plus opaque `refs`. The caregiver's speaker hears "You have 1 new CareLoop update", never the symptom |
| Patient-controlled consent | Scoped, expiring caregiver invitations; revocation is confirmed by voice and applies on the next request |
| Family task assignment | The patient assigns a task to a named family member; Alexa+ gets reminder suggestions; the family member is told they have a new task, with the details only when they ask; they mark it done; a missed task raises a generic update |
| Suggestions | "Anything I should know?" raises what is worth a look from the patient's own records: a visit coming up, a missed task, no check-in today, plan items waiting. Code decides, every suggestion is tied to its source, and nothing new is stored |
| Questions for the clinician | Saved by voice, never answered or read back, and placed in the next handoff |
| Multi-turn workflows | Check-ins ask follow-up questions from the approved plan; a guided voice review walks through draft items (change the time, give it to someone, skip, stop) and resumes later; CareLoop offers the next step; "move it to 8 pm" refers to the task just mentioned; a new "Alexa, …" request pauses a waiting workflow |
| Access transparency | "Who has seen my care data this week?" is answered from the audit log: who viewed or did what, never the content |
| Prescription intake | Upload a prescription (PDF, scan or photo): every proposed task cites its source line, invented numbers are blocked, and nothing reaches Alexa+ until the patient approves it |
| Clinician handoff | A date-bounded, cited factual summary rendered as an MCP Apps view |
| Data rights | Patient-scoped export, deletion, retention expiry, and purge |

See [docs/CARELOOP_FEATURES.md](docs/CARELOOP_FEATURES.md) for the full story and [docs/CARELOOP_ALEXA_PLUS_ROADMAP.md](docs/CARELOOP_ALEXA_PLUS_ROADMAP.md) for how this differs from native Alexa+.

## Prerequisites

| Requirement | Needed for | Check |
| --- | --- | --- |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | Everything | `uv --version` |
| Python 3.12+ (uv can install it) | Everything | `uv python list` |
| Git | Cloning | `git --version` |
| [Ollama](https://ollama.com) with a tool-calling model *(optional)* | LLM planner | `ollama list` |
| Any 64-bit Mac, Windows or Linux machine *(optional)* | Local speech: Kokoro and Whisper. Apple Silicon uses MLX Whisper, everything else uses faster-whisper (CPU, or an NVIDIA GPU if present). Models download on first use. | `uv run python -c "import platform; print(platform.machine())"` |
| Chrome *(recommended)* | Microphone input and browser speech fallback | — |

Without Ollama, the simulator uses its deterministic mock planner. If local speech is not installed or fails to load, the simulator uses the browser's own speech (`STT=browser`).

## Setup, step by step

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

**3. (Optional) Choose the local model and voice.** The demo runs with no settings at all, using a scripted planner and your browser's own speech. To use the local model and local voice, copy the example file and edit it:

```bash
cp .env.example .env        # Windows: copy .env.example .env
```

`.env` is Git-ignored and holds only three settings, the model and the two voice switches:

```text
LLM_MODEL=gemma4:e4b
# VOICE=kokoro      # remove the # on these two lines for local voice
# STT=whisper
```

Setting `LLM_MODEL` turns on the local planner. Leave it out to use the scripted one.

The first run downloads the voice models, and the simulator picks the right Whisper engine for your system. Every other setting has a default (see [Configuration](#configuration)).

**4. (Optional) Pull the local model**, if you set `LLM_MODEL` above:

```bash
ollama pull gemma4:e4b     # voice planner and document reading
```

Without a model the demo uses the scripted planner, and documents are read by pattern matching, so each item needs your review. If Ollama is not running, the simulator falls back to the scripted planner by itself.

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

Her prescription is *not* loaded: share it from the Alexa app panel. Because yesterday was a 7, a check-in of 7 or more today fires her approved rule. In Backstage, **Reset demo data** (click twice) restores this starting day at any time, with both devices linked. The video script is in [docs/CARELOOP_3MIN_VIDEO_DEMO.md](docs/CARELOOP_3MIN_VIDEO_DEMO.md).

| Variant | Command |
| --- | --- |
| Deterministic planner (stage-safe, exact replies as in the demo walkthrough) | `CARELOOP_AGENT_LLM=mock scripts/run_alexa_demo.sh` |
| Browser speech instead of Kokoro/Whisper | `VOICE=browser STT=browser scripts/run_alexa_demo.sh` |
| Restore the seeded starting day | `scripts/run_alexa_demo.sh --reset` |
| Day four at home: an approved plan with three days of history, for the [3-minute video](docs/CARELOOP_3MIN_VIDEO_DEMO.md) (suggestions, teach-back, handoff) | `scripts/run_alexa_demo.sh --reset --story=history` |
| Start with nothing (for the [demo walkthrough](docs/CARELOOP_DEMO_WALKTHROUGH.md) tables) | `scripts/run_alexa_demo.sh --empty` |
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

### Using the simulator

- **Devices:** *Maya's Echo Show* (patient, with a screen) and *Sam's Echo Dot* (caregiver, voice only).
- **Talk:** tap the 🎤 on a device and speak, or tick **Hands-free "Alexa…"** and pick which device hears you. Saying "stop" interrupts speech. Typing in a device's box, or tapping a prompt chip, does the same as speaking.
- **Alexa app panel:** **Enable CareLoop** links an account (synthetic credentials stay on the server). **Sam opens Maya's invitation link** simulates Sam accepting her invite.
- **Backstage panel:** switch the stand-in planner (OpenAI-compatible API ↔ Ollama ↔ mock), reset the conversation, ring the next simulated reminder, and **Reset demo data** (wipes only the demo patient and reseeds the starting day).
- **MCP inspector:** every `tools/list`, `tools/call`, `resources/read` and `elicitation/create` message, live.

## Demo walkthrough

The step-by-step walkthrough with the expected reply for every line is in **[docs/CARELOOP_DEMO_WALKTHROUGH.md](docs/CARELOOP_DEMO_WALKTHROUGH.md)**. It covers:

- the main story: plan approval, caregiver consent, check-in, the rule firing, privacy on a shared speaker, handoff, and revocation
- family tasks, clinician questions and the access log
- multi-turn conversations
- prescription intake from a PDF, scan or photo

For exact buttons and screens with screenshots, use the [click-by-click demo guide](docs/CARELOOP_UI_DEMO_GUIDE.md).

## Testing

```bash
uv run pytest -q                       # all 410 tests
uv run pytest -q server/tests          # MCP server, tools, consent, MCP Apps views, elicitation
uv run pytest -q alexa_sim/tests       # simulator host and scripted evaluator, incl. a live run of the demo story
```

The `alexa_sim` live test (`test_full_demo_story_against_live_careloop`) starts a real CareLoop server process with a temporary database and drives the demo walkthrough through the simulator API: linking, approval, invite and accept, the elicitation check-in, caregiver privacy, acknowledgement, handoff, and confirmed revocation.

Other checks:

```bash
uv run python scripts/e2e_careloop_demo.py      # API-level synthetic journey; sanitized report in .careloop-e2e/
uv run python evals/run_careloop.py --repeat 3  # 16 standalone eval cases with flakiness reporting
```

To inspect the MCP server with any standard MCP client, run `uv run careloop` and connect to `http://127.0.0.1:8010/mcp` with header `Authorization: Bearer careloop-local-demo-token`.

## MCP surface

Endpoint `http://127.0.0.1:8010/mcp` (Streamable HTTP, bearer token required). `GET /healthz` is public.

| Tool | Purpose |
| --- | --- |
| `import_care_plan_text` / `approve_plan_item` | Import synthetic plan text into source-cited drafts, then explicitly activate an item |
| `list_care_tasks` / `record_task_completion` | List plan items (counts + refs) and record completions |
| `get_care_plan_source` | Open a reviewed source excerpt in the private view |
| `start_daily_checkin` | Check-in that asks its own follow-up question via **MCP elicitation** |
| `record_pain_observation` / `correct_pain_observation` | Record a validated, idempotent 0–10 value; corrections keep history |
| `search_care_history` / `list_care_records` | Authorized, source-linked history (ISO dates or `last_N_days`) |
| `list_care_circle` / `invite_caregiver` / `accept_caregiver_invitation` / `revoke_caregiver` | Patient-controlled caregiver access (invitations can carry a name, e.g. "Sam") |
| `assign_task` / `list_my_assigned_tasks` | Assign a task to a family member with `perform_tasks`; they list and complete their own tasks. Results carry `reminders` for Alexa+ to create natively |
| `add_question_for_clinician` | Save a question for the next handoff; CareLoop never answers it |
| `review_plan_by_voice` | Guided, resumable review of draft items by voice (MCP elicitation per item); medicine and flagged items stay on screen |
| `update_task_time` | Move a task to a new spoken time ("8 pm", "9"), by name or id |
| `accept_data_use` | The patient accepts the one-time data-use disclosure; voice tools ask for it before first use |
| `set_my_details` | The patient's spoken name (used in family members' messages), time zone, and whether suggestions are on |
| `start_teach_back` | **Patient only.** Asks the patient to say back key plan values through elicitation and checks each answer in code; keeps only the structured value heard. Pauses on "stop" and resumes later |
| `get_suggestions` | **Patient only.** Up to three things worth raising now, each with an offer a "yes" can run (for example the visit handoff). Computed from approved records; never about symptoms |
| `who_accessed_my_care_data` | Who else viewed or acted on the patient's data (default: last 7 days) |
| `list_generic_notifications` / `acknowledge_alert` | Generic caregiver updates and new-task notices, as counts only ("You have 1 new task from Maya."). No alert detail and no task name; "mark it seen" clears them |
| `create_visit_handoff` | Date-bounded, cited handoff (ISO dates, epochs, or `last_7_days`) |
| `export_care_data` / `delete_care_record` | Patient data rights |
| `get_intake_status` | Status of the latest uploaded document: reading, ready with counts, or unreadable |
| `review_plan_item` | **App-only**: approve, edit the spoken name or times, or reject a draft on the patient's screen |
| `get_private_view` | **App-only** (`_meta.ui.visibility: ["app"]`): detail for MCP Apps views; hidden from the model |

**Voice-safe result contract.** Every model-visible tool returns structured content with these fields:

- `status`
- `speakable`: counts and statuses only, safe for a shared speaker
- `surface`
- `view`
- `refs`: opaque ids with position-based labels such as `draft task 1`

Failures are MCP tool errors with generic text. Each tool declares its MCP Apps view in `_meta.ui.resourceUri`. Those `ui://careloop/<view>` resources are static HTML shells that do the MCP Apps handshake and load detail only through `get_private_view`, which runs the same identity and consent checks. Destructive tools carry `destructiveHint` so hosts confirm first. Tool arguments never select another patient.

## Document intake

Patients, or family members the patient grants `upload_documents`, upload a prescription or discharge plan in the private view (`POST /api/care/documents/upload`) or through the simulator's Alexa app panel. Alexa+ doesn't pass user files to add-ons, so uploads never go through voice.

1. **PDF text layer** (`pypdf`) per page; a quality check sends empty or garbled pages to OCR.
2. **OCR fallback** (`PaddleOCR`, pages rendered with `pypdfium2`) for scanned pages and photos; each line keeps its confidence.
3. **LLM** (local Ollama by default, `gemma4:e4b`; or any OpenAI-compatible endpoint, see `CARELOOP_INTAKE_LLM`) receives numbered lines (`p1:L12`) fenced as data and returns schema-constrained JSON items that cite their lines.
4. **Deterministic checks:**
   - Citations must exist and the instruction must appear verbatim.
   - **Every number must appear in the source.**
   - Schedules come from a fixed frequency table.
   - Alert rules are accepted only in the supported form, with their numbers taken from the text.
   - Low-confidence OCR, conflicts and unused lines are surfaced.
   - Failures become **needs review**, never silently dropped.
   - If the model is unavailable, a pattern fallback runs and flags every item.
5. **Patient review** on screen: approve, edit the spoken name or times, or reject. Medicine and flagged items cannot be approved by voice. Raw extracted text expires after 24 h.

```bash
uv run python evals/intake/run_intake.py --model gemma4:e4b --repeat 3
```

On the synthetic set (typed, scanned, photo, injection), 3 runs each: recall 100%, invented numbers 0, citations valid, injection never followed. Median time per document: 8 s typed, 28 s photo, 41 s scanned (CPU OCR).

## Architecture

```mermaid
flowchart LR
  subgraph browser["Browser: assistant simulator"]
    show["Maya's Echo Show<br/>voice · screen · MCP App iframe"]
    dot["Sam's Echo Dot<br/>voice only"]
    app["Alexa app panel<br/>account linking"]
    insp["MCP inspector"]
  end
  subgraph host["alexa_sim host :8021"]
    orch["Turn loop<br/>planner · confirmations · elicitation"]
    pool["MCP client pool<br/>1 session per account"]
    voice["Kokoro TTS · Whisper STT"]
  end
  llm[("Stand-in for Alexa+'s model<br/>OpenAI-compatible API or Ollama")]
  subgraph careloop["CareLoop MCP server :8010"]
    mcp["/mcp tools · ui:// views"]
    core["Approval · consent · rules · handoff"]
    db[("SQLite/WAL")]
  end
  show & dot <--> orch
  orch --> llm
  orch --> pool --> mcp --> core --> db
  show <-. MCP Apps bridge .-> pool
  app --> pool
  voice --- show & dot
```

The simulator does what Alexa+ does for an MCP add-on:

- It discovers tools with `tools/list` and lets the model choose among them.
- It speaks only the `speakable` field.
- It renders the view declared on the tool definition in a sandboxed iframe.
- It answers elicitations by voice.
- It confirms destructive actions before running them.

The caregiver's ring is a **simulated push** (the host polls generic notifications), because Alexa+ MCP add-ons have no documented server push.

## Configuration

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
| `CARELOOP_DEMO_IDLE_RESET_MINUTES` | `0` (off) | The simulator restores the seeded demo after this many minutes without use |
| `CARELOOP_TIMEZONE` | this machine's zone | IANA zone for task times, reminders and missed-task checks (a patient's own setting wins) |
| `CARELOOP_INTAKE_LLM` | follows `CARELOOP_AGENT_LLM` (`openai` or `ollama`) | Document reading provider: `ollama`, `openai`, or `none` for pattern matching only. **With `openai`, the text extracted from a shared document is sent to that endpoint**; the privacy policy says so |
| `CARELOOP_INTAKE_MODEL` | `LLM_MODEL` | Model that structures uploaded documents |
| `CARELOOP_INTAKE_OCR` | `paddle` | OCR for scanned pages and photos (`none` sends them to manual review) |

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

## Repository layout

```text
server/care_loop/        CareLoop MCP server: tools, MCP Apps views, auth, core rules
  extraction/            PDF text layer + PaddleOCR fallback → numbered source lines
  structuring/           local-LLM schema, prompt, deterministic checks, pattern fallback
  tools/records.py       MCP tools and the voice-safe result contract
  ui/                    ui://careloop views (static MCP App shell)
alexa_sim/               the one simulator folder: Alexa+ behavior simulator and scripted evaluator
  backend/alexa_sim/     host: MCP client pool, turn loop, planners, voice engines, MCP Apps bridge
    evaluator/           scripted, deterministic eval harness used by evals/run_careloop.py
  frontend/              devices, Alexa app panel, inspector, speech capture
  tests/                 simulator and evaluator tests
evals/                   standalone eval cases; evals/intake/ synthetic documents + intake eval
samples/                 synthetic prescription PDF, scan, photo and prompt-injection documents
scripts/                 run, seed, and end-to-end scripts
docs/                    features, roadmap, demo walkthrough, UI guide, click-by-click guide, simulator walkthrough, friction log, evals, project story
```

Key documents:

- [Friction log](docs/FRICTION_LOG.md)
- [Evals](docs/CARELOOP_EVALS.md)
- [Demo walkthrough with expected replies](docs/CARELOOP_DEMO_WALKTHROUGH.md)
- [Click-by-click demo guide](docs/CARELOOP_UI_DEMO_GUIDE.md)
- [Driving the simulator end to end](docs/CARELOOP_SIMULATOR_WALKTHROUGH.md)
- [UI guide](docs/CARELOOP_UI_GUIDE.md)
- [Project story](docs/CARELOOP_PROJECT_STORY.md)

## Safety and privacy boundaries

- Public [privacy policy](http://127.0.0.1:8010/privacy) and [terms of use](http://127.0.0.1:8010/terms) pages are served by the CareLoop server (`/privacy`, `/terms`).
- Self-harm or medical-emergency words get emergency guidance (local emergency number; 988 in the US) and never reach a tool or model.

- Synthetic adult data only; no real patient records.

**Security decisions (MCP).** Choices made against the [MCP security best practices](https://modelcontextprotocol.io/docs/2026-07-28/tutorials/security/security_best_practices):

- **Static bearer tokens, not OAuth.** The Alexa+ MCP client doesn't support the `WWW-Authenticate` challenge yet, so `/mcp` answers 401 with a plain body. Account linking in a real deployment stays outside this adapter.
- **Identity comes from the credential.** Tool arguments never select a patient or caregiver, and returned refs are opaque, so holding a ref is not authentication.
- **Grants instead of protocol scopes.** Least privilege is enforced per patient through expiring caregiver grants.
- **No demo tokens off loopback.** The server exits at startup if it listens on a non-loopback address with the built-in demo tokens (`CARELOOP_ALLOW_DEMO_TOKENS` overrides).
- **Host and Origin allowlist.** DNS-rebinding protection is always on, including when bound to all interfaces. Add a tunnel hostname with `CARELOOP_ALLOWED_HOSTS`.
- **No token passthrough or proxying.** The server calls no downstream API with caller tokens.
- CareLoop is not medical advice and does not replace a clinician.
- Only reviewed, patient-approved, source-backed rules can create alerts.
- A notification is not confirmation that someone saw it, acted on it, or that care occurred.
- Raw uploads, clinical data in audit logs, and private details in generic alerts or spoken replies are prohibited by design.
- The simulator is not an Amazon product and is not a certified Alexa+ integration. Production use needs independent clinical, legal, security, privacy, identity/account-linking, accessibility, and device review.

## License

[MIT](LICENSE) © 2026 Imtiaz Ahammed
