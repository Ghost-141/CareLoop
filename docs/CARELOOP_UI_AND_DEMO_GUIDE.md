# CareLoop UI and demo guide

What the demo shows, how to run it yourself, and every screen in the repository. All data is synthetic, and the simulator is not an Amazon product: it stands in for Alexa+ in front of the same MCP server.

## The demo in brief

Maya comes home from a clinic visit with a prescription. Her brother Sam helps out. The demo follows them over four days.

1. **First visit.** Maya shares the prescription. CareLoop turns it into draft items, each beside the line it came from, and nothing is active until she approves it on her own screen.
2. **Day four.** Alexa raises what's worth a look from Maya's own records, then checks that she understood her plan by asking her to say it back. Her answers are checked in code against the prescription line.
3. **A rule fires.** Maya reports pain of 8. Her doctor's written rule (line 11) is met. Sam's speaker only says an update is waiting; his phone says which rule, never her score.
4. **Sam helps.** Maya gives Sam the dressing change. He sees only what she allows, and can tick off only his own task.
5. **Limits and handoff.** Alexa refuses medical advice without calling a tool, builds a visit summary where every claim cites its source, and removes Sam's access when Maya asks.

**What it means:** Alexa+ already remembers and reminds. CareLoop makes every care instruction traceable to its page, approved by the patient, checked for understanding, and shared only as far as she allows. *Alexa+ remembers. CareLoop proves.*

## Reproduce the demo

Install first ([setup guide](CARELOOP_SETUP.md)). No API key is needed: the scripted planner gives the same replies every run.

**Clip 1: first visit**

1. Run `CARELOOP_AGENT_LLM=mock scripts/run_alexa_demo.sh --reset` and open the URL it prints in Chrome.
2. In **Backstage**, press **Reset demo data**, then **Click again to reset**. This links Maya's Show and Sam's Dot.
3. On the phone's **Alexa app** tab: **Share a document** → Prescription → Typed PDF → **Share sample**.
4. Maya's Show opens the plan review: each item shows its source line (for example `p1:L5`). Tick each flagged item's check box, then **Add to my plan** on each card. Without a model every item is flagged, because it was read by pattern matching.

**Clip 2: day four** (stop the script with Ctrl+C)

5. Run `CARELOOP_AGENT_LLM=mock scripts/run_alexa_demo.sh --reset --story=history`, open the URL it prints, and press **Reset demo data** twice again.
6. Say or type these on **Maya's Show**, waiting for each reply:
   - `Alexa, anything I should know?` → suggestions, each with its source
   - `yes`, then `8 am`, then `7:30 in the morning` → teach-back: the wrong answer gets "Not quite. Try again", the right one passes
   - `Alexa, my pain is 8 today` → Sam's Dot ring lights; on **Sam's phone**, tap the notification to see which rule fired, then **Lock**
7. On **Sam's Dot**: `Alexa, what was Maya's pain score?` → "CareLoop records are unavailable."
8. On Maya's Show:
   - `Alexa, Sam handles the dressing change` → Sam's phone shows "Maya gave you a new task."
   - `Alexa, should I double my ibuprofen?` → no medical advice, no tool call
   - `Alexa, get me ready for my appointment` → the visit handoff
   - `Alexa, remove Sam`, then `confirm`
9. On Sam's Dot: `Alexa, what are my tasks for Maya?` → "You don't have access…"

The **MCP inspector** (Backstage → Inspector) shows every tool call behind each step. If something goes wrong, press **Reset demo data** twice in Backstage, or use the [troubleshooting table](CARELOOP_SETUP.md#troubleshooting).

## Screens

| Surface | For | Where |
| --- | --- | --- |
| [Alexa+ simulator](#1-alexa-simulator) | Demo presenter and judges | The URL `scripts/run_alexa_demo.sh` prints |
| [Private screens](#2-private-screens) | Maya on the Echo Show, Sam on his phone | Opened by tool results in the simulator |
| [Private portal](#3-private-portal) | Patient or caregiver in a plain browser | `http://127.0.0.1:8010/care` |
| [Product page](#4-product-page) | Public visitors | GitHub Pages, source in `site/` |

---

## 1. Alexa+ simulator

Maya's Echo Show, Sam's Echo Dot, a phone, Backstage, and the MCP inspector on one page. Source: `alexa_sim/frontend/`.

**Talking to a device:** type and press **Send**, or tap the **microphone**. **Things to say** lists one-tap requests. **Hands-free "Alexa"** listens for the wake word. Say **"stop"** to cut a reply short; after Alexa asks a question, just answer.

**Maya's Echo Show** shows the latest exchange, then the [private screen](#2-private-screens) a reply opens.

**Sam's Echo Dot** is voice only. The caption shows exactly what Sam hears. A **yellow ring** means a care update is waiting; details go to his phone, never the speaker.

**The phone** has two tabs:
- **Alexa app**: **Enable CareLoop / Unlink** for Maya and Sam, **Open Maya's invitation as Sam**, and **Share a document** (samples or your own PDF or photo).
- **Sam's phone**: a simulated CareLoop app. The lock screen says only that something is waiting; tap to see what Maya allows. **Mark done** appears only on Sam's own task.

**Backstage** (demo controls): **Planner** (Ollama, OpenAI-compatible API, or **Mock replay** for repeatable replies), **Reset conversation**, **Reset demo data** (press, then **Click again to reset**), **Ring next reminder**, **Inspector**.

**MCP inspector**: a live log of every request (`→`) and reply (`←`) between the simulated Alexa+ and the server, plus one `◆ turn` line per finished request.

---

## 2. Private screens

MCP Apps views (`ui://careloop/<view>`) in a sandboxed frame. They hold no data until they ask the server, which checks sign-in and consent like any tool. Source: `server/care_loop/ui/`.

Every item shows a **status** (green active or done, amber needs review, red revoked or missed) and the **source line** it came from.

| View | You can |
| --- | --- |
| **Plan review** | Edit, **Add to my plan**, or **Leave it out** each item read from a document |
| **Care tasks** | See what's worth raising and the plan by time; **Mark done** |
| **Care circle** | See who has access and who looked; **Remove** someone |
| **CareLoop updates** | **Mark as seen** (family member) |
| **Check-in trend**, **Understanding check**, **Visit handoff** | View pain scores, teach-back results, and a sourced summary for the clinician |

---

## 3. Private portal

`http://127.0.0.1:8010/care`. Sign in with `careloop-local-demo-token` (patient) or `careloop-local-caregiver-token` (caregiver). The patient can approve a plan, check in, manage sharing and make a handoff; the caregiver sees lists and can **Acknowledge** updates.

The server also serves `/privacy`, `/terms` and `/healthz`. Everything under `/mcp` needs a bearer token.

---

## 4. Product page

`site/index.html`: what CareLoop does, playable conversations, the limits, and how to run it.
