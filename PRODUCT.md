# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Two primary users, weighted equally:

- **The patient** (demo persona: Maya), at home after a clinic visit with a page of instructions. She shares the prescription or discharge plan, approves each proposed item on her Echo Show's private screen, records check-ins by voice, decides who in the family can see what and for how long, and takes a factual handoff to her next appointment.
- **The family caregiver** (demo persona: Sam), helping from a shared speaker such as an Echo Dot. Sam gets generic updates ("You have 1 new CareLoop update"), handles tasks the patient assigns to him, marks them done, and only sees what the patient's grant allows.

Secondary audiences: the clinician who receives the visit handoff, and, until the Oct 23, 2026 hackathon deadline, judges who meet CareLoop through the demo video, the simulator and the product page.

## Product Purpose

CareLoop turns a clinician-provided plan into a patient-controlled, accountable care loop, built as an MCP add-on for Alexa+. A shared document becomes cited draft items; nothing is active until the patient approves it. Check-ins, clinician-written rules, scoped family access and a dated handoff follow from the approved plan, and every step is an auditable MCP tool call.

Success means the patient and family know exactly what the plan says, who agreed to it, who can see it, why an update fired, and what the clinician will be told.

## Positioning

"Every care instruction Alexa says can be traced back to the page it came from."

Alexa+ can remember a document, set reminders and alert family about activity. CareLoop adds the accountable record behind those features: per-item patient approval with source-line citations, patient-owned expiring consent, deterministic rules that only a patient-approved, source-backed rule can trigger, privacy on shared speakers, and a cited clinician handoff.

## Operating Context

- **Surfaces:** voice on Echo devices; MCP Apps views (`ui://careloop/*`) on the Echo Show's private screen (plan review, tasks, plan source, care circle, notifications, check-in trend, visit handoff, records, history, export); the Alexa app for account linking and document sharing; a product page (`site/`).
- **Simulator:** with no Echo device or Alexa+ preview access, `alexa_sim/` simulates an Echo Show, an Echo Dot, the Alexa app and a live MCP inspector in the browser. It is not an Amazon product.
- **Documents:** typed PDFs, scanned PDFs and phone photos of prescriptions and discharge plans. PDF text is read first, PaddleOCR is the fallback, a local or OpenAI-compatible model proposes items, and deterministic checks decide what survives.
- **Rituals:** the clinic visit, taking medicines at set times, daily pain check-ins, family helping with tasks, and preparing for the next appointment.

## Capabilities and Constraints

- Detail never travels in a tool result. Results carry a short `speakable` line plus opaque refs; private detail appears only on the patient's private screen, and shared speakers never hear symptoms or scores.
- Identity comes from the credential; no tool argument can select another patient.
- MCP Apps views run in a sandboxed iframe with no same-origin access and no declared CSP, so they cannot load external fonts or assets. Record data is rendered as text, never parsed as HTML.
- CareLoop does not diagnose, prescribe, adjust medication, treat missing data as normal, promise emergency monitoring, or use real patient data.
- Intake: every number in a proposed item must appear in the source; anything that fails becomes "needs review" and is never silently dropped.
- Terminology: plan item, draft, needs review, approve, check-in, follow-up rule, care circle, grant, update (never "alert" on a shared speaker), visit handoff.
- Roadmap after the deadline: CareLoop continues as a real product. A real Alexa+ deployment needs OAuth 2.1 with PKCE, HTTPS and sub-500 ms responses; these are not built yet.

## Brand Commitments

- Name: CareLoop.
- Line: "Every care instruction Alexa says can be traced back to the page it came from."
- Required disclaimers wherever they apply: the simulator is not an Amazon product; all data is synthetic; CareLoop is not medical advice or emergency monitoring.

## Evidence on Hand

- Synthetic sample documents: `samples/prescription_typed.pdf`, `samples/prescription_scanned.pdf`, `samples/prescription_photo.png`, `samples/prompt_injection.pdf`.
- Intake evaluation on the synthetic set: 100% recall, zero invented numbers, every citation valid, planted instruction never followed (`evals/intake/`, `docs/CARELOOP_EVALS.md`).
- Live-model voice evaluation: 126/126 scenario runs passing after fixes (first run 96/108); failures recorded in `docs/FRICTION_LOG.md`.
- Automated test suite in `server/tests/` and `alexa_sim/tests/`.
- Absent, and not to be fabricated: real users, patients, clinicians, testimonials, partner organizations, clinical validation, pricing, or certification claims.

## Product Principles

1. **Traceable before helpful.** Every instruction points to its source line; nothing becomes active without the patient's approval.
2. **The patient owns the loop.** Consent is scoped, expiring and revocable by voice, and the patient sees who accessed what.
3. **Say less out loud.** Shared speakers hear generic updates; detail lives on the private screen.
4. **Rules decide, models propose.** Models suggest; deterministic checks and clinician-written rules make the decisions.
5. **Name the limits.** Gaps and failures are stated plainly, never dressed up as success.

## Accessibility & Inclusion

- Patients may be older or have low vision and read the Echo Show screen at arm's length: large type, strong contrast and generous touch targets are requirements, not polish.
- Caregivers may experience CareLoop through voice alone; what they hear must stand on its own.
