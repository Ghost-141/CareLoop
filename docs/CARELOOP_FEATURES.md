# CareLoop features and Alexa+ story

CareLoop is a synthetic adult-care coordination demo built as an MCP add-on for Alexa+. It helps a person keep clinician-provided instructions, their own observations, and approved caregiver support in one accountable loop. It is not a diagnostic, treatment, medication-adjustment, emergency-response, or real patient-record system.

## What CareLoop adds

Alexa+ supplies the conversational and multimodal layer: it can route a request to an add-on, generate the spoken response, maintain conversational continuity, and render either native data responses or an MCP App UI. CareLoop supplies the narrowly scoped care-coordination logic behind that experience: reviewed plan data, consent, deterministic rules, source citations, and a handoff for a clinician discussion. [Alexa+ MCP Toolkit overview](https://www.developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-overview.html) and [Alexa+ design introduction](https://developer.amazon.com/ja/docs/alexaplus/add-ons/mcp-addon-design-guide-overview.html)

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

What it deliberately does not do: diagnose, prescribe, change a dose, interpret a trend or missing data, invent an instruction, number or alert threshold, read a symptom or value aloud on a shared speaker, or claim to monitor for emergencies. See [CARELOOP_SECURITY.md](CARELOOP_SECURITY.md).

## A story: Maya's follow-up week

Maya leaves a routine follow-up visit with a simple, synthetic discharge plan. The plan says to complete two recovery tasks and to contact her clinician if her recorded pain score is at least 7 for two consecutive days. Maya opens CareLoop in her authenticated private view and uploads the plan.

CareLoop does not simply turn the upload into instructions. It shows Maya two draft tasks and one draft follow-up rule, each with a short source citation. Maya reviews them and explicitly activates them. The plan is now a patient-approved record rather than an opaque assistant memory.

Maya invites her brother Sam as a caregiver. She chooses only `read_tasks`, `receive_alerts`, and `acknowledge_alerts`. Sam can see what support tasks Maya has chosen to share, but he cannot browse the source document, export data, change the plan, or see observations just because he received an alert.

Over three days, Maya logs synthetic pain scores in her private view. Alexa+ makes the interaction natural: Maya can ask to see her active tasks or record a permitted task completion, while CareLoop provides the authenticated tool results and source-backed data. Complex, private detail remains in the authenticated CareLoop view; a shared or voice-style surface receives only the minimum appropriate status.

When Maya's second qualifying observation is recorded, CareLoop evaluates the exact rule she approved. It creates one alert episode. Sam receives only: **“CareLoop update available.”** He opens his own authenticated view and acknowledges the update. The acknowledgement is recorded without exposing Maya's clinical details in a generic notification.

Before the next appointment, Maya asks CareLoop to create a handoff for the week. It summarizes the plan sources, completed tasks, recorded observations, the alert and acknowledgement, and any corrections—clearly labelled as a patient-generated record for a clinician discussion. Maya then revokes Sam's access. His next request, including a stale page reload, is denied.

The value is not that an assistant decides what Maya needs. The value is that the care loop stays attributable: the clinician-provided source, Maya's approval, the recorded facts, the limited caregiver action, and the handoff all remain distinguishable.

## How it fits Alexa+

CareLoop is designed as an MCP add-on-shaped service, not as a replacement for Alexa+. Alexa+ MCP add-ons can expose tools/resources to the Alexa+ client, while Alexa+ handles natural-language understanding, response generation, and UI rendering. MCP Apps can render an interactive UI directly in the conversation view when data-only presentation is not enough. [MCP Toolkit overview](https://www.developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-overview.html)

For a future integration, CareLoop would use:

- **voice or keyboard for lightweight actions:** list approved tasks, record an allowed completion, or ask whether a source-linked record exists;
- **authenticated private UI for sensitive detail:** review a plan, grant/revoke consent, enter observations, inspect source citations, and review a handoff;
- **generic notifications:** signal that an update is available without reciting private content;
- **MCP Apps for visual workflows:** a dashboard can adapt across Alexa+ surfaces, but must treat the runtime as sandboxed and use the host bridge rather than relying on parent-window access, cookies, or persistent local storage. [Layout and rendering guide](https://developer.amazon.com/docs/alexaplus/add-ons/mcp-addon-layout-and-rendering.html)

This separation matters because Alexa+ policy requires clear purpose and consent for sensitive data and prohibits collecting or reciting private personal information by voice. Health-related experiences must attribute medical information, include an appropriate professional-advice disclaimer, and must not claim life-saving or emergency-intervention capabilities. [Alexa+ policy requirements](https://developer.amazon.com/zh/docs/alexaplus/add-ons/policy-requirements.html)

For actual user-specific access, a production integration needs user-level account linking and consent rather than the demo's fixed synthetic credentials. Alexa+ describes `authorization_code` with PKCE for user-level authentication, separate from service-level `client_credentials` access. [Alexa+ MCP authentication](https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-authentication.html)

## Demo boundaries

- All records and names in the demo are synthetic.
- CareLoop is not medical advice and does not replace a clinician.
- A notification is not a guarantee that a caregiver saw it, acted on it, or that care occurred.
- The current E2E demo proves application behavior; it does not prove Alexa+ certification or clinical safety.
- Any future Alexa+ add-on must undergo separate policy, account-linking, privacy, security, accessibility, and device testing. The Alexa+ Local Inspector can assess MCP data/UI behavior before on-device testing, but it does not replace real-device verification. [Local Inspector](https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-local-inspector.html)
