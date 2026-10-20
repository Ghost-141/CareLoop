# CareLoop

**Every care instruction Alexa says can be traced back to the page it came from.**

CareLoop is an MCP add-on for Alexa+. It turns a clinician's plan into tasks the patient approves and understands, family members can help with, and a clinician can trust. Every step is an auditable MCP tool call.

Built for the **Amazon Developer Hackathon 2026, Alexa+ track**. The repository includes an Alexa+ behavior simulator (`alexa_sim/`), which is **not an Amazon product**. All data is synthetic. CareLoop is not medical advice and does not monitor for emergencies.

**Product page:** [ghost-141.github.io/CareLoop](https://ghost-141.github.io/CareLoop/)

## What CareLoop adds to Alexa+

Alexa+ can read a document, set reminders and tell family about activity. CareLoop adds the accountable record behind them:

- **A plan the patient approves.** A shared prescription becomes draft items, each beside the line it came from. Code checks every number against the page, and nothing is active until the patient approves it.
- **Teach-back.** CareLoop asks the patient to say the plan back and checks each answer in code. A miss is answered by reading the line back, never by explaining it.
- **A source for every claim.** Every card on the patient's screen shows the document line, or the record it was worked out from.
- **Suggestions from her own history.** "Anything I should know?" raises a missed task, a visit coming up, or an answer to look at again, and says why.
- **Privacy on shared speakers.** Family hear "You have 1 new CareLoop update", never a symptom or a score. A helper is told a task is waiting, and what it is only when they ask.
- **Rules a clinician wrote.** Only an approved, source-backed rule can raise an alert, once per episode.
- **The patient in control.** Scoped, expiring family access, removable by voice; a visit handoff for the clinician; who looked at her data; export and delete.

The full list is in [docs/CARELOOP_FEATURES.md](docs/CARELOOP_FEATURES.md).

## Quick start

Needs [uv](https://docs.astral.sh/uv/getting-started/installation/) (it installs Python 3.12+ for you) and bash (macOS, Linux, or WSL/Git Bash on Windows).

```bash
git clone https://github.com/Ghost-141/CareLoop.git
cd CareLoop
uv sync --extra dev --extra alexa-sim --extra voice --extra intake --extra ocr
uv run python evals/intake/documents.py    # synthetic sample documents
scripts/run_alexa_demo.sh                  # then open http://127.0.0.1:8021
```

It runs with no settings: a scripted planner, pattern matching for documents, and the browser's own speech. To use a hosted model (any OpenAI-compatible API) or a local one (Ollama), and local voice, copy `.env.example` to `.env` and follow [docs/CARELOOP_SETUP.md](docs/CARELOOP_SETUP.md).

Run the tests:

```bash
uv run pytest -q       # 410 tests, including live runs against a real server
```

## Try the demo

| Start with | Command | What it shows |
| --- | --- | --- |
| The first visit | `scripts/run_alexa_demo.sh --reset` | Share the prescription, review and approve it, then everything that follows |
| Day four at home | `scripts/run_alexa_demo.sh --reset --story=history` | Three days of history: suggestions, teach-back, the rule firing, the handoff |

## Documentation

| Document | What's in it |
| --- | --- |
| [Setup, running and testing](docs/CARELOOP_SETUP.md) | Prerequisites, install, demo variants, the simulator, tests, troubleshooting |
| [Configuration](docs/CARELOOP_CONFIGURATION.md) | Every environment variable and its default |
| [Architecture](docs/CARELOOP_ARCHITECTURE.md) | Components, the MCP tools and voice-safe results, document intake, repository layout |
| [Safety, privacy and security](docs/CARELOOP_SECURITY.md) | What CareLoop never does, and the MCP security decisions |
| [Features](docs/CARELOOP_FEATURES.md) | Every capability, and how it fits Alexa+ |
| [UI guide](docs/CARELOOP_UI_GUIDE.md) | Every screen and control |
| [Simulator walkthrough](docs/CARELOOP_SIMULATOR_WALKTHROUGH.md) | Driving the simulator end to end |
| [Evals](docs/CARELOOP_EVALS.md) | Document-reading and live-model voice evaluations |
| [Friction log](docs/FRICTION_LOG.md) | What was hard building for Alexa+, and open questions for the Alexa+ team |
| [Project story](docs/CARELOOP_PROJECT_STORY.md) | Why we built it and what we learned |

## License

[MIT](LICENSE) © 2026 Imtiaz Ahammed
