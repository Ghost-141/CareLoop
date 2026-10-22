# CareLoop UI guide

Every screen in the repository. All data is synthetic.

| Surface | For | Where |
| --- | --- | --- |
| [Alexa+ simulator](#1-alexa-simulator) | Demo presenter and judges | The URL `scripts/run_alexa_demo.sh` prints |
| [Private screens](#2-private-screens) | Maya on the Echo Show, Sam on his phone | Opened by tool results in the simulator |
| [Private portal](#3-private-portal) | Patient or caregiver in a plain browser | `http://127.0.0.1:8010/care` |
| [Product page](#4-product-page) | Public visitors | GitHub Pages, source in `site/` |

The simulator is not an Amazon product. It stands in for Alexa+ in front of the same MCP server.

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
