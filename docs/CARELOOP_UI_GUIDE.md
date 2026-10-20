# CareLoop UI guide

Every screen in the repository, what each section shows, and what you can do in it. All data is synthetic.

## The surfaces at a glance

| Surface | Who it is for | Address | Started by |
| --- | --- | --- | --- |
| [Alexa+ simulator](#1-alexa-simulator) | Demo presenter and judges | `http://127.0.0.1:8021` | `scripts/run_alexa_demo.sh` |
| [Private screens (MCP App views)](#2-private-screens-shown-on-the-echo-show) | The patient, inside the simulator's Echo Show | Served by the MCP server as `ui://careloop/<view>` | Opened by tool results |
| [Private portal](#3-private-portal) | Patient or caregiver, in a plain browser | `http://127.0.0.1:8010/care` | The MCP server |
| [Product page](#4-product-page) | Public visitors | GitHub Pages, source in `site/` | Published by the pages workflow |
| [Policy pages](#5-server-pages) | Alexa+ policy reviewers | `/privacy`, `/terms` on the MCP server | The MCP server |

The simulator is not an Amazon product. It behaves like Alexa+ in front of the same MCP server so the add-on can be tested without a device.

---

## 1. Alexa+ simulator

One page with five areas: a top bar, Maya's Echo Show, Sam's Echo Dot, a simulated Alexa app, and a Backstage panel. Source: `alexa_sim/frontend/` (`index.html`, `sim.js`, `sim.css`).

### 1.1 Top bar

| Control | What it does |
| --- | --- |
| **Hands-free "Alexa"** switch | Listens continuously for the wake word. When it hears "Alexa, …" it sends the rest to the device chosen in the next control. A bare "Alexa" arms the mic for about 6 seconds for the next phrase. |
| **Heard by** | Chooses which device receives hands-free speech: Maya's Show or Sam's Dot. |
| Voice engine text | Shows what speaks and listens: Kokoro and Whisper once the local models are ready, otherwise the browser's own speech. It updates while models load. |
| Status text | Short messages such as microphone permission needed or which listener is active. |

### 1.2 Maya's Echo Show (patient, with a screen)

| Part | What it shows or does |
| --- | --- |
| **State label** (top right of the card) | The device state: `idle`, `listening`, `thinking` or `speaking`. |
| **Screen: home** | Clock and date, with a hint to enable CareLoop and say "Alexa, …". |
| **Screen: conversation** | The latest exchange only, as speech bubbles: what Maya said and what the device answered. Like a real Show, older bubbles drop off. System notes (for example "The private view couldn't load.") appear here too. |
| **Screen: private view slot** | The sandboxed [private screen](#2-private-screens-shown-on-the-echo-show) that opens after a tool result, such as the plan review. It is replaced when a new view opens and cleared by Reset conversation. |
| **Light bar** | Under the screen. It pulses while listening and speaking and sweeps while thinking. |
| **Microphone button** | Tap to speak. A second tap ends the utterance early. The button highlights while live. With Whisper, it stops on silence (about 0.8 s) or after 12 s, and gives up if nothing is said for 7 s. |
| **Text box and Send** | Type a request instead of speaking. Typing while the mic is open cancels the mic. |
| **Prompt chips** | One-tap example requests for the patient: import a plan, approve it, invite Sam, check-in, "anything I should know?", record pain, appointment handoff, who has access, remove Sam, medical-advice question, document status, family tasks, clinician question, access log, voice review, and "move it to 8 pm". |

Behaviors that apply to both devices:
- **Interrupting:** saying or typing "stop", "quiet" or "cancel that" stops speech immediately. Speaking again also interrupts.
- **Follow-up questions:** after a question or confirmation prompt (for example the daily check-in's "what's your pain score?"), the mic reopens by itself so the person can just answer.
- **Review steps:** if a voice review step changed what is on screen, the open view refreshes.
- **Announcements:** replies pushed by the server (for example "Your document is ready…") are spoken and shown without a request.

### 1.3 Sam's Echo Dot (caregiver, voice only)

| Part | What it shows or does |
| --- | --- |
| **State label** | Same four states as the Show. |
| **Light ring** | A circle that changes with the state: blue while listening and speaking, spinning while thinking, grey while idle. **A pulsing yellow ring means Sam has a new CareLoop update.** A new task is announced in words ("Maya gave you a new task.") and does not light the ring. The ring clears once the update is acknowledged ("mark it seen"). |
| **Caption** | Exactly what Sam hears, shown as text. Until he speaks it reads "Voice only. This caption shows exactly what Sam hears." Private detail never appears here, only the spoken line. |
| **Microphone, text box, Send** | Same as the Show. |
| **Prompt chips** | Updates, mark it seen, "what was Maya's pain score?" (a privacy probe, answered with no value), "show Maya's tasks", "what are my tasks for Maya?", and "I've done Maya's evening task". |

The Dot never gets a screen. Its private views and the app-only data tool are refused by the host.

### 1.4 Alexa app panel (simulated)

This panel plays the part of the phone app. The synthetic credentials behind it stay on the server and never reach the browser or the private views.

| Part | What it does |
| --- | --- |
| **Maya: Enable CareLoop / Unlink** | Links or unlinks the patient account. On link, the inspector notes how many model-visible tools were discovered. A device only answers CareLoop requests after its account is linked. |
| **Sam: Enable CareLoop / Unlink** | Same for the caregiver account. |
| **Open Maya's invitation as Sam** | Simulates Sam opening the invitation link Maya's voice request created. Enabled only when an invitation is pending and Sam's Dot is linked. Sam's Dot then says the invitation was accepted. |
| **Share a document with CareLoop** | Simulates sharing a file from the phone. Choose **From** (Maya or Sam), **Type** (Prescription or Discharge plan), then **Choose a PDF or photo** and **Share file**. Accepts PDF, PNG and JPEG. |
| **Or use a sample** | Shares a built-in synthetic document without a file: **Typed PDF**, **Scanned PDF (OCR)**, **Phone photo (OCR)** or **Prompt-injection test**. |
| Share status line | Reports progress: Sending, "CareLoop is reading it…", an error, or "Ready for Maya to review" when the Show receives the finished review. |
| **Privacy policy / terms links** | Open the server's `/privacy` and `/terms` pages. |

Documents never travel by voice, because Alexa+ does not pass user files to add-ons. Sam can only share if Maya granted him the upload permission.

### 1.5 Backstage (demo controls, not part of the product)

| Control | What it does |
| --- | --- |
| **Planner** | Switches who chooses tools: the **Local LLM (Ollama)** or the deterministic **Mock replay** (exact, stage-safe replies). |
| **Reset conversation** | Clears both devices' conversation memory, the on-screen bubbles and the open private view. It does not change stored care data. |
| **Ring next reminder** | Delivers the next simulated Alexa+ reminder (for example a family member's task reminder). Disabled until a reminder exists. The count line says how many are set and which is next. |
| **Reset demo data** | Wipes only the demo patient's records and restores Maya's seeded starting day with both devices linked. It needs two clicks within 4 seconds to guard against accidents. The note shows if an idle auto-reset is configured. |
| **Show MCP inspector** | Shows or hides the inspector below. |

### 1.6 MCP inspector

A live log, newest first, of everything between the simulated Alexa+ and the MCP server. At most 150 lines are kept.

| Line | Meaning |
| --- | --- |
| `→ method [account] …` | A request sent to the server (`tools/call` with the arguments, `resources/read` with the view URI, and so on). |
| `← method [account] …` | The reply: the tool result, the tool list, or a byte count for a view. Results that are errors are flagged. |
| `◆ turn [device · planner] tools: a → b · "reply"` | One finished request: which planner ran, the tools it called in order, and the spoken reply. |
| Host and error lines | Account linking messages and failures. |

An `elicitation/create` line marks a question the server asked mid-tool, such as the check-in question.

### 1.7 Device states

| State | Show screen | Dot ring | Light bar |
| --- | --- | --- | --- |
| `idle` | Home or latest exchange | Grey (yellow pulse if an update is waiting) | At rest |
| `listening` | Unchanged | Blue glow | Pulsing |
| `thinking` | Unchanged | Spinning | Sweeping |
| `speaking` | Unchanged | Blue pulse | Fast pulse |

---

## 2. Private screens shown on the Echo Show

These are the MCP Apps views. A tool result names a view in its metadata, the Show loads that view into the sandboxed frame, and the view fetches its detail through an app-only tool. Source: `server/care_loop/ui/` (`app.html` and the view list in `__init__.py`).

**How they stay private**
- The view file is a static shell with no data in it. Detail arrives only through `get_private_view`, which runs the same sign-in and consent checks as every other tool.
- The frame is sandboxed with no cookies, storage or access to the page around it.
- All record text is drawn as plain text, never as HTML.
- The header note reads "Private to this screen. Alexa won't read it aloud." If a view isn't permitted, it says "This view isn't available here. Open CareLoop on your private screen."
- The footer reminds the person that the data is synthetic and not medical advice.

**Common building blocks**
- **Status pills:** green for active, approved, done, accepted; amber for draft, needs review, pending, processing; red for revoked, rejected, failed, missed, expired.
- **Source slips:** the exact line the item came from, with page or line id. Lines read by OCR show their confidence, and low-confidence lines are marked "Check this line".
- **Flag notes:** a small flag icon beside anything that needs a closer look.

| View | Opened by | What it shows | Actions |
| --- | --- | --- | --- |
| **Plan review** | Importing a plan, document ready, reviewing | Document summary (title, how it was read, follow-up date, notes), then "N items to check" as review cards, then "Already in your plan", then a collapsed list of lines that did not become plan items | On each card: edit the **spoken name** and **times**, tick "I've checked this against the document" when the item is flagged, **Add to my plan**, or **Leave it out**. A processing document shows "Reading…" and refreshes itself. |
| **Care tasks** | Listing or changing tasks | Active plan items sorted by time with their status, who handles each ("Sam handles this"), and the source line | **Mark done** on an active task |
| **Plan source** | Opening a source | The document excerpts that approved items came from, under "From your clinician" | None |
| **Care circle** | Inviting, listing or revoking caregivers | **People with access** with status, permissions and end date, and **Who looked at your care data** for the last 7 days (what each person viewed or did, never the content) | **Remove** on active or pending access |
| **CareLoop updates** | Caregiver notifications | Generic updates, and a "New task" row when the patient has given you a task, with the note that the details come only when you ask | **Mark as seen** |
| **Check-in trend** | Check-ins and rules | A pain chart from 0 to 10 with a dashed alert line from the approved rule, red points at or above it, and a list of check-ins newest first. Corrections are marked. Missing days are never filled in. | None |
| **Visit handoff** | Preparing for an appointment | A row of totals (plan items, tasks done, missed, check-ins, alerts, questions, corrections), then questions for the clinician, the plan with its source lines, completed tasks, check-ins, alerts, and notes about gaps | None |
| **CareLoop records** | Listing records | One row per record with its kind, status and date | None |
| **History search** | Searching history | The records that matched, in the same list form | None |
| **Data export** | Exporting data | An "Export ready" summary with the record count and time, then the included records | None |

Caregivers see only what their grant covers, and the Dot never receives a view.

---

## 3. Private portal

A plain web page for a patient or caregiver who is not using the simulator. Address: `http://127.0.0.1:8010/care`. Source: `server/care_loop/portal.py`.

**Sign in.** Paste a demo token and choose **Continue securely**. The token is kept only for the browser session and is never shown. The default patient token is `careloop-local-demo-token` and the default caregiver token is `careloop-local-caregiver-token`. A notice at the top says the page is a demo, not medical advice.

After sign-in, the top right shows "Patient · private session" or "Caregiver · private session". The navigation has **Today**, **Plan review**, **Track**, **Sharing**, **Handoff** and **Sign out**.

### Patient views

| View | Sections | Actions |
| --- | --- | --- |
| **Today** | Today's tasks; Recent check-ins; Private sharing; Your plan | **Mark complete** on an active task; buttons to jump to Sharing and Plan review |
| **Plan review** | Review plan items (each marked task or clinician-sourced rule, with its status); Import a synthetic plan | **Approve item** on drafts; import by entering a title and `TASK:` / `RULE:` lines |
| **Track** | Observation history; Add a check-in | Enter a pain score from 0 to 10 and **Save check-in** |
| **Sharing** | Caregiver access (permissions, expiry, status); Invite a caregiver | **Revoke**; choose one permission, an optional expiry, and **Create invitation** |
| **Handoff** | Visit handoff form and result | Enter the start and end as Unix timestamps and **Generate handoff** |

### Caregiver views

| View | What it shows |
| --- | --- |
| **Today** | **Action-required updates** (generic only, with an **Acknowledge** button), **Your access** (a note that the patient controls it), and **Tasks shared with you** |
| **Plan review**, **Track**, **Sharing** | Lists only. Caregivers are not shown the forms to approve items, import a plan, add a check-in, invite or revoke. |
| **Handoff** | Explains that only the patient can generate one |

Messages after an action appear as a short toast at the bottom right.

---

## 4. Product page

The public page for the project. Source: `site/index.html`, with `privacy.html` and `terms.html` beside it. Header links: How it works, In conversation, Safety, For developers, GitHub.

| Section | Content |
| --- | --- |
| **Hero** | "Every care instruction Alexa says can be traced back to the page it came from." |
| **Alexa+ remembers. CareLoop proves.** | What CareLoop adds beyond native Alexa+ features |
| **How the loop works** | Five steps: share the plan, approve each item, bring in family, check in daily, hand off to the clinician. Below them, an animated diagram with a Play button follows one prescription through Alexa+ and the CareLoop server. |
| **What it sounds like** | Four example conversations: consent, a shared speaker that knows when to stop, reviewing a plan one item at a time, and a prescription becoming a plan with proof |
| **What CareLoop never does** | The safety boundaries |
| **See it running** | A simulator screenshot, a placeholder for the three-minute video, and four facts (tool count, intake accuracy, test count, local operation) |
| **For developers** | How to run and connect the MCP server |
| **What comes next** | Planned work |

---

## 5. Server pages

Served by the MCP server on port 8010.

| Path | Purpose |
| --- | --- |
| `/privacy` | Privacy policy: what the server stores and for how long |
| `/terms` | Terms of use |
| `/healthz` | A public health check that reports status ok and the version. Everything under `/mcp` needs a bearer token. |
| `/care` | The [private portal](#3-private-portal) |

---

## Which surface should I use?

| I want to… | Use |
| --- | --- |
| Run the full Alexa+ story with two devices and a phone | The Alexa+ simulator |
| Show the exact messages between Alexa+ and the server | The MCP inspector in Backstage |
| Review or approve a plan as the patient on a screen | The Plan review private screen, or the portal's Plan review |
| See a caregiver's limited view | Sam's Dot in the simulator, or the portal signed in with the caregiver token |
| Check what an Alexa+ policy reviewer will read | `/privacy` and `/terms` |
| Show the project to someone who hasn't run it | The product page |
