# CareLoop features and Alexa+ story

CareLoop is a synthetic adult-care coordination demo built as a standalone MCP service. It helps a person keep clinician-provided instructions, their own observations, and approved caregiver support in one accountable loop. It is not a diagnostic, treatment, medication-adjustment, emergency-response, or real patient-record system.

## What CareLoop adds

Alexa+ supplies the conversational and multimodal layer: it can route a request to an add-on, generate the spoken response, maintain conversational continuity, and render either native data responses or an MCP App UI. CareLoop supplies the narrowly scoped care-coordination logic behind that experience: reviewed plan data, consent, deterministic rules, source citations, and a handoff for a clinician discussion. [Alexa+ MCP Toolkit overview](https://www.developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-overview.html) and [Alexa+ design introduction](https://developer.amazon.com/ja/docs/alexaplus/add-ons/mcp-addon-design-guide-overview.html)

| Capability | What CareLoop does | What it deliberately does not do |
| --- | --- | --- |
| Private plan intake | Accepts bounded synthetic text plans; retains a hash and short cited excerpts, not raw uploads. | It does not treat a PDF or model output as an automatically active care plan. |
| Reviewed tasks and rules | Creates drafts, requires patient approval, and links active items to their source. | It does not invent instructions, medication dosage, or thresholds. |
| Patient-owned consent | Lets the patient issue expiring caregiver invitations with specific scopes and revoke them immediately. | It does not infer consent from a shared device, a speaker name, or a family relationship. |
| Longitudinal observations | Records fixed, validated observations such as a synthetic 0–10 pain score, with timestamps, actors, idempotency, and corrections. | It does not diagnose a trend or interpret missing information as normal. |
| Deterministic follow-up | Evaluates only an approved, source-backed rule and creates at most one alert per episode. | It does not invent risk thresholds or promise monitoring/emergency intervention. |
| Privacy-preserving alerts | Gives authorized caregivers a generic case/status notification and a scoped acknowledgement action. | It does not include symptoms, medications, observations, or plan text in the notification. |
| Visit handoff | Produces a date-bounded, source-cited factual summary of plan items, recorded observations, task events, alerts, acknowledgements, and corrections. | It does not claim to be a clinical conclusion or substitute for a clinician. |
| Search and data rights | Provides patient-scoped history retrieval plus export, deletion, expiry, and physical purge of source and derived data. | It does not mix data across patients or retain deleted records in its search index. |
| Evaluation and demo | Includes isolated repeatable eval cases and a synthetic E2E journey. | It does not represent a certified Alexa+ integration or real-world clinical validation. |

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
