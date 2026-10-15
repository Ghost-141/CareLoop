# CareLoop: three-minute end-to-end video demo

> This script records the original voice simulator (`care_sim`, port 8020). For the Alexa+-style two-device demo with the MCP inspector, use `scripts/run_alexa_demo.sh` (port 8021) and the story in the README section "Alexa+ behavior simulator" and `docs/CARELOOP_ALEXA_SIM_DEMO_PLAN.md`.

This is a local, synthetic demonstration. Do not use real patient information, show `.env`, or display tokens, database paths, raw MCP inspector data, or model logs in the recording.

## What the video proves

1. A patient controls plan approval, care-circle access, and revocation.
2. CareLoop records a structured check-in but gives no medical interpretation.
3. A caregiver sees only a generic update, not clinical details.
4. CareLoop creates a factual, date-bounded handoff with source attribution.
5. Voice is conversational, but CareLoop keeps authorization and data boundaries deterministic.

## One-time preflight

From the CareLoop project root, install the project and make sure the configured Ollama model is available:

```bash
uv sync --extra dev
ollama list
# Only if qwen3.5:4b-mlx is not listed:
ollama pull qwen3.5:4b-mlx
```

Use the existing `.env` with these voice settings:

```dotenv
CARELOOP_AGENT_LLM=ollama
LLM_MODEL=qwen3.5:4b-mlx
VOICE=browser
STT=browser
```

`VOICE=browser` and `STT=browser` are the most reliable recording setup. They use browser speech output/input when available, while typed input remains the stage-safe fallback.

## Recording setup

Use a fresh, clearly named synthetic database for the recording. The seed creates a fictional recovery-coordination journey with completed and active routine tasks, four changing check-ins, one generic threshold update, and a visit handoff. These commands remove only the specified demo database files if they already exist.

If another CareLoop or voice-simulator process already uses ports `8010` or `8020`, stop it with `Ctrl-C` before starting this clean recording setup.

### Terminal 1 — Ollama

```bash
ollama serve
```

If Ollama is already running as a desktop service, leave it running and skip this terminal.

### Terminal 2 — seed and run CareLoop

```bash
cd /Users/imtiaz/Projects/CareLoop
export CARELOOP_DB_PATH="$PWD/.careloop-video-demo.db"
rm -f "$CARELOOP_DB_PATH" "$CARELOOP_DB_PATH-shm" "$CARELOOP_DB_PATH-wal"
uv run python scripts/seed_careloop_demo.py
uv run careloop
```

### Terminal 3 — start the voice surface

```bash
cd /Users/imtiaz/Projects/CareLoop
export CARELOOP_DB_PATH="$PWD/.careloop-video-demo.db"
scripts/run_careloop_voice_demo.sh
```

Open these two tabs before recording:

- Patient workspace: [http://127.0.0.1:8010/care](http://127.0.0.1:8010/care)
- Voice experience: [http://127.0.0.1:8020](http://127.0.0.1:8020)

In the patient workspace, sign in with the local synthetic demo token from your own `.env`; never put the token on screen. Confirm that the seeded plan, check-ins, and handoff are visible.

## Three-minute shot list

| Time | Screen and action | Say |
| --- | --- | --- |
| 0:00–0:15 | Start on **Today** in the patient workspace. Show the synthetic-demo and not-medical-advice notices. | “CareLoop turns a clinician-provided plan into a patient-controlled coordination loop. This demo uses only synthetic data.” |
| 0:15–0:38 | Open **Plan review**. Point out patient-approved tasks and source-aware review. | “Nothing becomes active simply because it was imported. The patient reviews and explicitly approves plan items, preserving source attribution.” |
| 0:38–0:58 | Open **Track**. Show the existing check-ins, then switch to the voice tab and type: `record the pain score as 8 out of 10`. | “A patient can record a bounded check-in by voice. CareLoop stores the structured value; it does not diagnose, interpret, or recommend treatment.” |
| 0:58–1:18 | Stay on the voice tab and type: `show my tasks`. Let the Ollama-generated response play/read. | “Ollama makes the response conversational, but it receives only CareLoop’s approved safe summary. The MCP server remains the authorization authority.” |
| 1:18–1:42 | Return to **Sharing**. Show the caregiver permissions UI. | “Sharing is granular and patient-controlled. Caregivers get only the scopes the patient grants; sensitive history is not automatically shared.” |
| 1:42–2:04 | Use the terminal briefly to run the verified E2E proof below; show only the `PASS` lines. | “The same workflow is verified end to end: scoped caregiver access, generic notification acknowledgement, and immediate denial after revocation.” |
| 2:04–2:30 | Open **Handoff**. In a terminal, obtain a two-day range with the command below, enter the two values, then select **Generate handoff**. | “For an appointment, CareLoop creates a factual handoff from approved plan items, observations, alerts, and source citations. It is patient-generated and date-bounded.” |
| 2:30–2:48 | Back on the voice tab, type: `what should I take for pain?` | “CareLoop declines diagnosis and medication guidance. It stays in the coordination lane and directs clinical decisions to qualified care.” |
| 2:48–3:00 | End on Today or the CareLoop title/notice. | “CareLoop makes care coordination visible and consent-driven across private screens and conversational entry points—without treating voice as permission to expose private care data.” |

## Verified end-to-end proof (show only `PASS` lines)

Run this in a fourth terminal while recording the 1:42–2:04 segment:

```bash
cd /Users/imtiaz/Projects/CareLoop
scripts/run_careloop_demo.sh
```

This uses a separate temporary database and proves the complete synthetic journey without changing the database shown in the browser: intake and approval, scoped caregiver access, observations and a rule episode, generic notification acknowledgement, date-bounded handoff, and denied requests after revocation.

## Handoff date inputs

For the Handoff shot, run this in a terminal and enter the two printed values as **From** and **To** respectively. This uses macOS's UTC `date` command:

```bash
date -u -v-2d +%s
date -u +%s
```

## Stage fallback

If Ollama or browser audio is unavailable, keep the same typed prompts in the voice page and say: “This recording uses typed input as the device-independent fallback; the same authenticated CareLoop workflow is running underneath.” Do not claim a model response when the voice model is offline.

After recording, stop the terminals with `Ctrl-C`. The scoped `.careloop-video-demo.db` files may be removed when no longer needed.
