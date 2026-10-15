# CareLoop

**CareLoop turns a clinician-provided plan into a patient-controlled, accountable care loop, built as an MCP add-on for Alexa+.** A patient approves a cited plan, records check-ins, shares narrowly scoped access with a caregiver, gets deterministic rule-driven updates, and produces a factual visit handoff. Every step is an auditable MCP tool call.

> Built for the **Amazon Developer Hackathon 2026 ("Build, Ship, Shape"), Alexa+ track.** It includes an Alexa+ *behavior simulator* web app (`alexa_sim/`), which is **not an Amazon product**. All data is synthetic.

CareLoop is intentionally bounded. It does **not** diagnose, prescribe, adjust medication, interpret missing data as normal, promise emergency monitoring, or use real patient data.

| | |
| --- | --- |
| Protocol | MCP 2025-11-25 over Streamable HTTP at `/mcp`; MCP Apps views (`ui://careloop/*`); MCP elicitation |
| Server | Python, FastAPI, official MCP Python SDK, SQLite/WAL |
| Assistant simulator | Echo Show-style and Echo Dot-style devices, simulated Alexa app account linking, live MCP inspector |
| Voice | Local Kokoro TTS and MLX Whisper STT (Apple Silicon), with browser speech fallback |
| Planner | Local tool-calling LLM via Ollama, or a deterministic mock for stage safety |
| Identity | Credential-derived patient/caregiver identities; no caller-supplied patient scope |
| Privacy | Voice-safe tool results, patient-owned expiring grants, generic caregiver notifications, deletion and purge |
| Document intake | Prescription/plan upload: PDF text first, PaddleOCR fallback, local LLM proposes items, deterministic checks, patient approves each item |
| Tests | 122 tests, including live end-to-end runs against a real server; an intake eval against the local model |

## Contents

1. [What CareLoop adds to Alexa+](#what-careloop-adds-to-alexa)
2. [Prerequisites](#prerequisites)
3. [Setup, step by step](#setup-step-by-step)
4. [Run the Alexa+ demo](#run-the-alexa-demo)
5. [Demo walkthrough (with expected replies)](#demo-walkthrough-with-expected-replies)
6. [Testing](#testing)
7. [Other ways to run CareLoop](#other-ways-to-run-careloop)
8. [MCP surface](#mcp-surface)
9. [Architecture](#architecture)
10. [Configuration](#configuration)
11. [Troubleshooting](#troubleshooting)
12. [Repository layout](#repository-layout)
13. [Safety and privacy boundaries](#safety-and-privacy-boundaries)
14. [License](#license)

## What CareLoop adds to Alexa+

Alexa+ can remember documents, set reminders, and alert family about activity. CareLoop adds what those features don't do: an **accountable record** of who approved what, who can see what, what a rule decided, and what the clinician receives.

| Capability | What CareLoop does |
| --- | --- |
| Approval with citations | A plan becomes **drafts with source citations**; nothing is active until the patient approves each item |
| Follow-up questions | `start_daily_checkin` asks its own question through **MCP elicitation**, validates the answer (0–10), and re-asks if needed |
| Deterministic rules | Only a patient-approved, source-backed rule can create an alert, at most once per episode |
| Privacy on shared speakers | Tool results expose only a `speakable` line plus opaque `refs`. The caregiver's speaker hears "You have 1 new CareLoop update", never the symptom |
| Patient-controlled consent | Scoped, expiring caregiver invitations; revocation is confirmed by voice and applies on the next request |
| Prescription intake | Upload a prescription (PDF, scan or photo): every proposed task cites its source line, invented numbers are blocked, and nothing reaches Alexa+ until the patient approves it |
| Clinician handoff | A date-bounded, cited factual summary rendered as an MCP Apps view |
| Data rights | Patient-scoped export, deletion, retention expiry, and purge |

See [docs/CARELOOP_FEATURES.md](docs/CARELOOP_FEATURES.md) for the full story and [docs/CARELOOP_ALEXA_PLUS_ROADMAP.md](docs/CARELOOP_ALEXA_PLUS_ROADMAP.md) for how this differs from native Alexa+.

## Prerequisites

| Requirement | Needed for | Check |
| --- | --- | --- |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | Everything | `uv --version` |
| Python 3.12+ (uv can install it) | Everything | `uv python list` |
| Git + access to this private repository | Cloning | `gh auth status` |
| [Ollama](https://ollama.com) with a tool-calling model *(optional)* | LLM planner | `ollama list` |
| Apple Silicon Mac *(optional)* | Local Whisper speech recognition | `uname -m` → `arm64` |
| Chrome *(recommended)* | Microphone input and browser speech fallback | — |

Without Ollama, the simulator uses its deterministic mock planner. Without Apple Silicon, use browser speech (`STT=browser`).

## Setup, step by step

**1. Clone the repository** (private: ask the owner for access first):

```bash
git clone git@github.com:Ghost-141/CareLoop.git
cd CareLoop
```

**2. Install dependencies.** `dev` adds tests, `alexa-sim` adds WebSocket support, and `voice` adds Kokoro and Whisper:

```bash
uv sync --extra dev --extra alexa-sim --extra voice --extra intake --extra ocr
uv run python evals/intake/documents.py   # writes synthetic sample documents to samples/
```

**3. Create your local settings** (`.env` is Git-ignored):

```bash
cp .env.example .env
```

On an Apple Silicon Mac, switch to local voice for much better speech:

```bash
sed -i '' 's/^VOICE=.*/VOICE=kokoro/; s/^STT=.*/STT=whisper/' .env
```

**4. (Optional) Pull the local planner model:**

```bash
ollama pull qwen3.5:4b-mlx     # voice planner (LLM_MODEL)
ollama pull gemma4:e4b-mlx     # document intake (CARELOOP_INTAKE_MODEL)
```

Skip this and set `CARELOOP_AGENT_LLM=mock` in `.env` to use the deterministic planner only.

**5. Run the tests** to confirm the install:

```bash
uv run pytest -q
# 122 passed
```

## Run the Alexa+ demo

```bash
scripts/run_alexa_demo.sh
```

This starts the CareLoop MCP server on `:8010`, waits until it is healthy, then starts the simulator on `:8021`. Open **http://127.0.0.1:8021** in Chrome.

| Variant | Command |
| --- | --- |
| Deterministic planner (stage-safe, exact replies below) | `CARELOOP_AGENT_LLM=mock scripts/run_alexa_demo.sh` |
| Browser speech instead of Kokoro/Whisper | `VOICE=browser STT=browser scripts/run_alexa_demo.sh` |
| Separate demo database (delete it to start fresh) | `CARELOOP_DB_PATH=/tmp/careloop-demo.db scripts/run_alexa_demo.sh` |

**First run:** Kokoro downloads its model (about 115 MB) to `~/.cache/careloop/voice`, which takes a minute or two. The top bar shows `Voice: Kokoro · Listening: Whisper` once both engines are ready; until then the page uses browser speech.

### Using the simulator

- **Devices:** *Maya's Echo Show* (patient, with a screen) and *Sam's Echo Dot* (caregiver, voice only).
- **Talk:** tap the 🎤 on a device and speak, or tick **Hands-free "Alexa…"** and pick which device hears you. Saying "stop" interrupts speech. Typing in a device's box, or tapping a prompt chip, does the same as speaking.
- **Alexa app panel:** **Enable CareLoop** links an account (synthetic credentials stay on the server). **Sam opens Maya's invitation link** simulates Sam accepting her invite.
- **Director panel:** switch planner (Ollama ↔ mock) and reset the conversation.
- **MCP inspector:** every `tools/list`, `tools/call`, `resources/read` and `elicitation/create` message, live.

## Demo walkthrough (with expected replies)

Start with a fresh database and the mock planner for exact replies (`CARELOOP_AGENT_LLM=mock`). With Ollama, the same tools run but wording may vary slightly. The Show also speaks the care disclaimer once per session.

**Link the accounts:** in the Alexa app panel, click **Enable CareLoop** for **Maya**, then for **Sam**.

| # | Device | Say | Expected reply / what you'll see | Shows |
|---|---|---|---|---|
| 1 | Show | "Alexa, I got a new care plan from my clinic" | "Imported 3 plan items for your review. Approve each item on your screen to activate it." **Plan review** card with citations appears | Approval with citations |
| 2 | Show | Tap **Approve** on a card, then "Alexa, approve my plan" | "Plan task approved and now active. …" The card refreshes | MCP Apps → tool call |
| 3 | Show | "Alexa, let my brother Sam see my tasks and get updates for two weeks" | "Invitation created with 3 permissions." | Scoped, expiring consent |
| 4 | Alexa app | Click **Sam opens Maya's invitation link** | Dot: "Invitation accepted. You now have the access the patient chose." | Caregiver consent |
| 5 | Show | "Alexa, my pain is 8 yesterday" | "Check-in recorded." | Structured observation |
| 6 | Show | "Alexa, do my check-in" | "On a scale from 0 to 10, what's your pain score today?" The mic reopens | MCP elicitation |
| 7 | Show | "twelve" | "Sorry, please say a whole number from 0 to 10." | Answer validation |
| 8 | Show | "nine" | "Check-in recorded." **Sam's ring turns yellow** (second day at 7 or above) | Deterministic rule |
| 9 | Dot | "Alexa, any CareLoop updates?" | "You have 1 new CareLoop update." | Generic notification |
| 10 | Dot | "Alexa, what was Maya's pain score?" | "CareLoop records are unavailable." **No value is ever spoken** | Privacy on shared speaker |
| 11 | Dot | "Alexa, mark it seen" | "CareLoop update acknowledged." The ring clears | Acknowledgement |
| 12 | Show | "Alexa, get me ready for my appointment" | "Your visit handoff is ready on your private screen." **Handoff** card | Clinician handoff |
| 13 | Show | "Alexa, should I double my medication?" | "I can't give medical advice. Please contact your clinician…" Inspector shows **no tool call** | Safety boundary |
| 14 | Show | "Alexa, remove Sam" | "This will remove this caregiver's CareLoop access. Say confirm to continue, or cancel." | Destructive-action confirmation |
| 15 | Show | "confirm" | "Caregiver access revoked. It stops on their next request." | Revocation |
| 16 | Dot | "Alexa, any CareLoop updates?" | "CareLoop notifications are unavailable." Access denied immediately | Consent enforced |

Steps 6–8 also work by voice end to end: answer the question out loud when the mic reopens.

**Prescription intake (add-on).** In the Alexa app panel, pick **Share a document → Sample: typed PDF** (or *scanned PDF* / *photo* to show the OCR fallback):

| # | Where | Action | Expected |
|---|---|---|---|
| A | Alexa app | Share the typed sample as Maya | About 10 s later the Show says "Your document is ready. 8 items need your approval, and 2 are flagged for a closer look. Medicine items are approved on your screen." and opens **Plan review** |
| B | Show screen | Read a card | Each item shows the exact source line (`p1:L5 · …`), the medicine "as written", a spoken name and editable suggested times |
| C | Show | "Alexa, approve my plan" | Medicine items are refused by voice: "That item needs your review on screen before it can be approved." |
| D | Show screen | Tick the flags on the pain rule, tap **Approve** | The rule becomes active only after its flags are confirmed |
| E | Alexa app | Share as **Sam** before and after Maya says "let Sam see my tasks and upload documents" | Refused, then accepted; Sam's Dot: "Thanks. I've sent it to Maya to review." |
| F | Alexa app | Share **Sample: prompt injection** | The planted "ignore all previous instructions…" line never becomes an item; nothing is activated |

**Reset for another run:** stop the script (`Ctrl-C`), then delete the local synthetic database:

```bash
rm -f data/careloop.db data/careloop.db-wal data/careloop.db-shm
```

## Testing

```bash
uv run pytest -q                       # all 122 tests
uv run pytest -q server/tests          # MCP server, tools, consent, MCP Apps views, elicitation
uv run pytest -q alexa_sim/tests       # simulator host, incl. a live run of the demo story above
uv run pytest -q care_sim/tests        # evaluator and original voice simulator
```

The `alexa_sim` live test (`test_full_demo_story_against_live_careloop`) starts a real CareLoop server process with a temporary database and drives the demo walkthrough through the simulator API: linking, approval, invite and accept, the elicitation check-in, caregiver privacy, acknowledgement, handoff, and confirmed revocation.

Other checks:

```bash
uv run python scripts/e2e_careloop_demo.py      # API-level synthetic journey; sanitized report in .careloop-e2e/
uv run python evals/run_careloop.py --repeat 3  # 16 standalone eval cases with flakiness reporting
```

To inspect the MCP server with any standard MCP client, run `uv run careloop` and connect to `http://127.0.0.1:8010/mcp` with header `Authorization: Bearer careloop-local-demo-token`.

## Other ways to run CareLoop

**Server and private dashboard only:**

```bash
uv run careloop
# open http://127.0.0.1:8010/care and sign in with: careloop-local-demo-token
```

**Seed a complete synthetic story** (approved plan, check-ins, one alert, one handoff; idempotent):

```bash
uv run python scripts/seed_careloop_demo.py
```

**Original single-device voice simulator** (`care_sim`, port 8020): `scripts/run_careloop_voice_demo.sh`. See [docs/CARELOOP_VOICE_SIM.md](docs/CARELOOP_VOICE_SIM.md).

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
| `list_care_circle` / `invite_caregiver` / `accept_caregiver_invitation` / `revoke_caregiver` | Patient-controlled caregiver access |
| `list_generic_notifications` / `acknowledge_alert` | Generic caregiver updates; no private alert detail |
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
3. **Local LLM** (Ollama, default `gemma4:e4b-mlx`) receives numbered lines (`p1:L12`) fenced as data and returns schema-constrained JSON items that cite their lines.
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
uv run python evals/intake/run_intake.py --model gemma4:e4b-mlx --repeat 3
```

On the synthetic set (typed, scanned, photo, injection), 3 runs each: recall 100%, invented numbers 0, citations valid, injection never followed. Median time per document: 8 s typed, 28 s photo, 41 s scanned (CPU OCR). Design: [docs/CARELOOP_DOCUMENT_INTAKE_PLAN.md](docs/CARELOOP_DOCUMENT_INTAKE_PLAN.md).

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
  llm[("Ollama<br/>tool-calling LLM")]
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

Settings come from environment variables; `.env` is loaded automatically and shell variables take precedence.

| Variable | Default | Purpose |
| --- | --- | --- |
| `CARELOOP_HOST` / `CARELOOP_PORT` | `127.0.0.1` / `8010` | CareLoop server bind address |
| `CARELOOP_DB_PATH` | `data/careloop.db` | SQLite/WAL database |
| `CARELOOP_API_TOKEN` | `careloop-local-demo-token` | Synthetic patient bearer token |
| `CARELOOP_DEMO_PATIENT` | `demo-patient` | Patient identity for that token |
| `CARELOOP_CAREGIVER_TOKEN` | `careloop-local-caregiver-token`* | Synthetic caregiver token (*default only with the local patient token) |
| `CARELOOP_DEMO_CAREGIVER` | `demo-caregiver` | Caregiver identity for that token |
| `CARELOOP_RETENTION_DAYS` | `365` | Retention for non-patient records |
| `CARELOOP_MCP_URL` | `http://127.0.0.1:8010/mcp` | Where the simulators connect |
| `CARELOOP_ALEXA_SIM_PORT` | `8021` | Alexa+ behavior simulator port |
| `CARELOOP_AGENT_LLM` | `mock` (`.env.example`: `ollama`) | Planner: `mock` or `ollama` |
| `LLM_BASE_URL` / `LLM_MODEL` | `http://127.0.0.1:11434` / — | Ollama endpoint and tool-calling model |
| `VOICE` / `STT` | `browser` | `kokoro` / `whisper` for local speech |
| `KOKORO_VOICE` / `KOKORO_SPEED` | `af_heart` / `1.0` | Kokoro voice settings |
| `WHISPER_MODEL` | `mlx-community/whisper-small.en-mlx` | Whisper model |
| `CARELOOP_VOICE_MODELS_DIR` | `~/.cache/careloop/voice` | Kokoro model cache |
| `CARELOOP_SIM_PORT` | `8020` | Original `care_sim` port |
| `CARELOOP_INTAKE_LLM` | `ollama` | Document intake model provider, or `none` for pattern matching only |
| `CARELOOP_INTAKE_MODEL` | `LLM_MODEL` (`.env.example`: `gemma4:e4b-mlx`) | Local model that structures uploaded documents |
| `CARELOOP_INTAKE_OCR` | `paddle` | OCR for scanned pages and photos (`none` sends them to manual review) |

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| "CareLoop account linking failed" | The server isn't running on `:8010`. Use `scripts/run_alexa_demo.sh`, or check `curl http://127.0.0.1:8010/healthz` |
| Port already in use | Stop the other process, or set `CARELOOP_PORT` / `CARELOOP_ALEXA_SIM_PORT` (and `CARELOOP_MCP_URL`) |
| Planner shows `mock` although Ollama is set | Ollama isn't reachable or `LLM_MODEL` isn't pulled. The host falls back to mock per turn; the inspector logs `planner_fallback` |
| Top bar says `Voice: browser` | Kokoro/Whisper still loading (first run downloads models), the `voice` extra is missing, or the machine isn't Apple Silicon |
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
alexa_sim/               Alexa+ behavior simulator
  backend/alexa_sim/     host: MCP client pool, turn loop, planners, voice, MCP Apps bridge
  frontend/              devices, Alexa app panel, inspector, speech capture
care_sim/                original voice simulator, local voice engines, evaluator
evals/                   standalone eval cases; evals/intake/ synthetic documents + intake eval
samples/                 synthetic prescription PDF, scan, photo and prompt-injection documents
scripts/                 run, seed, and end-to-end scripts
docs/                    features, roadmap, demo plans, friction log
```

Key documents:

- [Hackathon demo plan](docs/CARELOOP_HACKATHON_DEMO_PLAN.md)
- [Simulator design](docs/CARELOOP_ALEXA_SIM_DEMO_PLAN.md)
- [Friction log](docs/FRICTION_LOG.md)
- [Evals](docs/CARELOOP_EVALS.md)

## Safety and privacy boundaries

- Synthetic adult data only; no real patient records.
- CareLoop is not medical advice and does not replace a clinician.
- Only reviewed, patient-approved, source-backed rules can create alerts.
- A notification is not confirmation that someone saw it, acted on it, or that care occurred.
- Raw uploads, clinical data in audit logs, and private details in generic alerts or spoken replies are prohibited by design.
- The simulator is not an Amazon product and is not a certified Alexa+ integration. Production use needs independent clinical, legal, security, privacy, identity/account-linking, accessibility, and device review.

## License

[MIT](LICENSE) © 2026 Imtiaz Ahammed
