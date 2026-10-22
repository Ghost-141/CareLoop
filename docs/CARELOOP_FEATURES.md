# CareLoop features

CareLoop is an adult-care coordination MCP add-on for Alexa+, shown here with synthetic data. It helps a person keep clinician-provided instructions, their own observations, and approved caregiver support in one accountable loop. It is not a diagnostic, treatment, medication-adjustment, emergency-response, or real patient-record system.

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
