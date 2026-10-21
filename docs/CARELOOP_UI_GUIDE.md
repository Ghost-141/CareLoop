# CareLoop UI guide

Every screen in the repository and what you can do in it. All data is synthetic.

| Surface | For | Where |
| --- | --- | --- |
| [Alexa+ simulator](#1-alexa-simulator) | Demo presenter and judges | The URL `scripts/run_alexa_demo.sh` prints (usually `http://127.0.0.1:8021`) |
| [Private screens](#2-private-screens) | The patient on the Echo Show, and Sam on his phone | Opened by tool results inside the simulator |
| [Private portal](#3-private-portal) | Patient or caregiver in a plain browser | `http://127.0.0.1:8010/care` |
| [Product page](#4-product-page) | Public visitors | GitHub Pages, source in `site/` |
| [Server pages](#5-server-pages) | Policy reviewers | `/privacy` and `/terms` on the MCP server |

The simulator is not an Amazon product. It behaves like Alexa+ in front of the same MCP server, so the add-on can be tried without a device.

---

## 1. Alexa+ simulator

One page: Maya's Echo Show, Sam's Echo Dot, a phone (the Alexa app and Sam's phone), Backstage, and the MCP inspector. Source: `alexa_sim/frontend/`.

If port 8021 is busy, the script picks the next free port and prints it. Open the URL it prints.

### Talking to a device

- **Type** in a device's box and press **Send**, or tap the **microphone** and speak (tap again to finish early).
- **Things to say** under each device lists one-tap example requests.
- **Hands-free "Alexa"** (top bar) listens for the wake word and sends what follows to the device chosen in **Heard by**.
- Say **"stop"** to cut a reply short. After Alexa asks a question, the mic reopens so you can just answer.
- Each device shows its state: `idle`, `listening`, `thinking` or `speaking`.

### Maya's Echo Show (patient)

- The screen shows the latest exchange, then the [private screen](#2-private-screens) a reply opens, such as the plan review.
- The light bar under the screen glows while listening, sweeps while thinking, and pulses while speaking.

### Sam's Echo Dot (family member, voice only)

- The **caption** shows exactly what Sam hears. Private detail never appears there.
- A **yellow ring** means a care update is waiting, for example when Maya's pain rule fires. A new task is said in words ("Maya gave you a new task.") and doesn't light the ring.
- The Dot never shows a screen. When it can only give counts (for example "show Maya's tasks"), it says "I've sent the details to your phone."

### The phone

Two tabs at the top.

**Alexa app**
- **Enable CareLoop / Unlink** for Maya and for Sam. A device answers CareLoop requests only after its account is linked.
- **Open Maya's invitation as Sam** accepts an invitation Maya made by voice.
- **Share a document**: choose who shares it and the type, then **Share sample** (typed PDF, scanned PDF, phone photo, or a prompt-injection test) or pick your own PDF or photo and **Share file**. Sharing the same document again adds nothing twice.

**Sam's phone** (a simulated CareLoop app)
- Opens by itself when Sam gets a notification. The lock screen says only that something is waiting.
- Tap the notification to unlock. The CareLoop view opens as Sam, showing only what Maya allowed. **Mark done** appears only on Sam's own task.
- **Lock** closes the view.

### Backstage (demo controls, not part of the product)

- **Planner**: who chooses the tools. **Ollama** or an **OpenAI-compatible API** stands in for Alexa+'s model; **Mock replay** gives exact, repeatable replies.
- **Reset conversation**: clears both devices' memory and screens. Care data stays.
- **Reset demo data**: restores the starting story with both devices linked. Press it, then **Click again to reset** within 4 seconds.
- **Ring next reminder**: delivers the next simulated Alexa+ reminder.
- **Inspector**: shows or hides the MCP inspector.

### MCP inspector

A live log of everything between the simulated Alexa+ and the MCP server, newest first.

- `→` a request (`tools/call` with its arguments, or `resources/read`). `←` the reply. Errors are flagged.
- `◆ turn` one finished request: the device, the planner, the tools called in order, and the reply.

---

## 2. Private screens

MCP Apps views, served as `ui://careloop/<view>` and loaded into a sandboxed frame on Maya's Show or Sam's phone. Source: `server/care_loop/ui/`.

They stay private: the view holds no data until it asks the server, which checks sign-in and consent like any other tool. The frame has no cookies, storage or access to the page around it, and all record text is drawn as plain text.

**What you'll see on them**
- **Status**: a coloured dot and a word. Green is active or done, amber needs review or pending, red is revoked, failed or missed.
- **Source slip**: the exact line an item came from, highlighted. OCR lines show their confidence; low ones say "Check this line".
- **Because**: for anything worked out from records, the record it came from.

| View | Shows | You can |
| --- | --- | --- |
| **Plan review** | Items read from a document, each with its source line; flagged items to check | Edit the name and times, **Add to my plan**, or **Leave it out** |
| **Care tasks** | For Maya, **Worth raising** first; then the plan by time, and who handles each task | **Mark done** (Sam: only his own tasks) |
| **Care circle** | Who has access, and who looked at the data in the last 7 days | **Remove** someone |
| **CareLoop updates** | Generic updates and new-task notices for a family member | **Mark as seen** |
| **Check-in trend** | Pain scores over time with the rule's alert line | View only |
| **Understanding check** | Each teach-back question and its result, with the line | View only |
| **Visit handoff** | A dated summary for the clinician: questions, plan, understanding check, tasks, check-ins and alerts, each with its source | View only |
| **Plan source**, **Records**, **History**, **Export** | The document lines, the record list, search results, an export | View only |

---

## 3. Private portal

A plain web page for a patient or caregiver outside the simulator: `http://127.0.0.1:8010/care`. Source: `server/care_loop/portal.py`.

Sign in by pasting a demo token: `careloop-local-demo-token` (patient) or `careloop-local-caregiver-token` (caregiver). The token lasts only for the browser session.

- **Patient**: **Today** (tasks, check-ins), **Plan review** (approve items, import a synthetic plan), **Track** (add a pain check-in), **Sharing** (invite or revoke a caregiver), **Handoff** (generate one for a date range).
- **Caregiver**: the same pages as lists only, plus **Acknowledge** on updates. Only the patient can change the plan, sharing or handoff.

---

## 4. Product page

The public page, `site/index.html`. It shows Alexa citing her answer's source line, one update at three levels of detail (Sam's speaker, lock screen and phone), teach-back, where every claim comes from, the loop, playable conversations, the limits, the evidence, and how to run it.

---

## 5. Server pages

On the MCP server (port 8010): `/privacy`, `/terms`, `/healthz` (public status check), and `/care` (the portal). Everything under `/mcp` needs a bearer token.

---

## Which surface should I use?

| I want to… | Use |
| --- | --- |
| Run the full story with two people and two devices | The simulator |
| See the exact messages between Alexa+ and the server | The MCP inspector |
| Approve a plan as the patient | The Show's Plan review, or the portal |
| See what a family member gets | Sam's Dot and Sam's phone, or the portal with the caregiver token |
| Show the project to someone who hasn't run it | The product page |
