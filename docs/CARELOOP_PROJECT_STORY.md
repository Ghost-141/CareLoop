# CareLoop

**Every care instruction Alexa speaks can be traced back to the page it came from.**

## Inspiration

After a clinic visit, a patient goes home with a page of instructions. Take this at 8 AM. Call if the pain stays high. Someone in the family is supposed to help, and nobody is sure who. Alexa+ can remember a document and set a reminder, but it cannot show who approved a plan, who can see it, why an alert fired, or what the clinician should be told.

We wanted an assistant that is accountable, not just helpful. That meant a plan the patient approves item by item, access the patient controls, and rules written by a clinician instead of guessed by a model.

## What it does

CareLoop is an MCP add-on for Alexa+. A patient shares a prescription. CareLoop reads it, proposes tasks that each cite their exact source line, and activates nothing until the patient approves. From then on:

- **Check-ins:** Alexa asks the questions the plan defines, and the server validates every answer.
- **Rules:** a clinician's rule decides when family are told something. With threshold $\theta = 7$ and window $k = 2$ days, an alert fires once per episode when

$$s_{t-k+1}, \dots, s_t \ge \theta, \qquad s_i \in \{0, 1, \dots, 10\}.$$

- **Shared speakers:** Sam's Echo Dot hears "You have 1 new CareLoop update", never the pain score.
- **Family:** tasks can be given to a named person, with reminders.
- **Teach-back:** the patient says back when they take each medicine and the alert rule's numbers; code checks each answer against the cited line, and a miss is answered by reading the plan back, never by explaining.
- **Handoff:** a dated, cited summary for the clinician, including questions the patient saved and what the teach-back found.
- **Data rights:** export, delete, and revoke access by voice.

## How we built it

CareLoop is a Python MCP server (FastAPI, the official MCP SDK, SQLite) that exposes 32 tools over Streamable HTTP. Identity comes from the credential, so no tool argument can select another patient.

**Voice-safe results.** Every tool returns a short `speakable` sentence plus opaque references. Detail reaches the patient only through MCP Apps screens on the Echo Show.

**Document intake.** The pipeline reads the PDF text layer, falls back to PaddleOCR for scans and photos, and asks a local model (Ollama) to propose items. Deterministic checks then decide what survives. For every number $n$ in a proposed item, $n$ must appear in the source:

$$\mathrm{nums}(\text{item}) \subseteq \mathrm{nums}(\text{source}).$$

Anything that fails becomes "needs review" and is never silently dropped.

**A simulator.** We had no Echo device and no Alexa+ preview access, so we built a browser simulator of two devices, the Alexa app, local voice (Kokoro and Whisper), and a live MCP inspector. It is not an Amazon product.

**Evaluation.** Beyond 218 automated tests, we ran the real voice planner with a local model against a live server, 42 spoken scenarios three times each.

## Challenges we ran into

- **No access to Alexa+.** Building a faithful stand-in took real effort, and it still cannot prove the real client behaves the same way.
- **Small models invent things.** Our planner made up plan text, used an expiry date in the past, and granted seven permissions for a request that named two. The server now refuses or reads back instead of trusting the model.
- **Privacy versus usability.** Hiding every record from tool results made action tools unusable because they had no ids. Opaque, position-labelled references solved it.
- **Failures that sounded like success.** Early errors came back as normal replies, so Alexa could say "done" when nothing happened. Failures are now real tool errors.
- **The model confirming for the host.** Tool descriptions told the model to confirm destructive actions, so it asked its own question and the person's "yes" did nothing. Only a run with the real model showed this, and the fix was to rewrite those descriptions.
- **A protocol in motion.** The newest MCP revision is stateless and delivers questions differently, so our mid-call questions work under 2025-11-25 but not yet 2026-07-28. We documented the limit instead of hiding it.

## Accomplishments we're proud of

On our synthetic prescription set (typed, scanned, photographed, and prompt-injected), document reading reached

$$\text{recall} = \frac{|\text{found} \cap \text{expected}|}{|\text{expected}|} = 100\%,$$

with zero invented numbers, every citation valid, and the planted instruction never followed.

The live-model evaluation first passed $96/108 \approx 88.9\%$ of runs. After fixing the four failing behaviors it passed $126/126 = 100\%$ of a larger set of scenarios, and the failures are recorded in a friction log for the Alexa+ team.

## What we learned

- **Test with the real model.** A scripted planner passed everything the live one failed.
- **Do not ask the model to do what the host already does.** Fewer instructions made it more reliable.
- **Make the server the authority.** Identity, consent, validation, and rules belong in code that can be tested, not in a prompt.
- **Say what you could not verify.** Documenting limits earned more trust than hiding them.

## What's next

Real Alexa+ deployment with OAuth account linking once preview access opens. Alerts by text or push with escalation when nobody acknowledges. More of the plan, such as sleep and mood check-ins. A time-limited share link for the clinician.

CareLoop is a demonstration with synthetic data. It is not medical advice and does not monitor for emergencies.

## Built with

Python, FastAPI, MCP (Model Context Protocol), MCP Apps, SQLite, Ollama (gemma4), PaddleOCR, pypdf, Kokoro, MLX Whisper, JavaScript
