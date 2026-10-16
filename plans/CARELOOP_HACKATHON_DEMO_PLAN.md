# CareLoop on Alexa+: hackathon demo plan

**Deadline:** Devpost submission **Thu Oct 23, 2026, 12:00 PM PDT** (Fri Oct 24, 1:00 AM in Dhaka, GMT+6). Today is Wed Oct 15, so there are 8 days.
**Deliverables:** public repo (code must actually call MCP), demo video **under 3:00**, project description, Amazon product feedback. A friction log of setup problems is reported to be worth up to a **10% bonus**.

## 1. The idea: prove it twice

The demo has to show two things at once. The track accepts either one, and doing both is the strongest entry.

| Proof | What it shows | Where |
|---|---|---|
| **A. It is a real Alexa+ add-on** | The *unchanged* CareLoop MCP server, deployed with `alexa-ai deploy`, answers Alexa+ in Amazon's own web simulator, ideally on a physical Echo too. | Amazon web simulator / Echo device |
| **B. What it adds to Alexa+** | The full care loop across **two people and two devices**: patient approval, a caregiver with limited access, a rule-driven alert, a refused privacy question, revocation. One developer account on one real device can't show this. | CareLoop assistant simulator (`alexa_sim`) |

The line that connects them, which must be literally true: ***"Same MCP server, same tools, same results: first in Amazon's simulator, then the full two-person story."***

### The capabilities the video must make undeniable

Each maps to a moment in the script (section 3):

1. **Approval with citations:** a plan becomes *drafts with citations*, and nothing is active until the patient approves it. *(Alexa+ remembers documents; CareLoop makes them provable.)*
2. **Follow-up question from the add-on:** the server asks the check-in question mid-call (MCP elicitation), validates the answer and re-asks if needed.
3. **Rule-driven, not guessed:** a patient-approved, source-backed rule fires exactly once. There is no diagnosis.
4. **Privacy on a shared speaker:** the caregiver's Echo Dot hears "You have 1 new CareLoop update", never the symptom. Asking for the pain score is refused.
5. **Consent the patient controls:** limited, expiring access, confirmed by voice before revoking, and the next request is denied immediately.
6. **Clinician handoff:** a date-bounded, cited summary on screen.
7. **Proof it's real:** the MCP inspector shows tool discovery, calls, elicitation and app-only data calls live.

## 2. Work needed before recording

### Track A: real Alexa+ deployment (highest risk, start Day 1)

| # | Task | Why | Est. |
|---|---|---|---|
| A0 | **Gate check:** confirm the Alexa developer account has Alexa+ add-on access, `alexa-ai configure` works, and the web simulator opens. Check whether a physical Alexa+ Echo is available. **Alexa+ is US-centric, so a Bangladesh account or device may not get it.** | Decides whether proof A is a real-device clip or a web-simulator clip | 1 h |
| A1 | **OAuth 2.1 + PKCE (S256)** on the CareLoop server: `/oauth/authorize` (a demo login page to pick a synthetic patient or caregiver), `/oauth/token` (needs `resource` and `code_verifier`), RFC 9728 protected-resource metadata, and `/.well-known/oauth-authorization-server` with `code_challenge_methods_supported: ["S256"]`. Tokens map to the existing `Identity`. | Required for user-level account linking | 1 day |
| A2 | **Done.** **Remove the `WWW-Authenticate` header** from the 401 in `auth.py` (`BearerAuthMiddleware`). Alexa+ says it isn't supported yet. | Compliance | 10 min |
| A3 | **Public HTTPS:** a named `cloudflared` tunnel with a stable hostname, plus `/privacy` and `/terms` pages served by CareLoop (required listing URLs). | Alexa+ needs a remote HTTPS endpoint | 2 h |
| A4 | **Latency under 500 ms round trip:** measure `tools/call` through the tunnel. Keep SQLite local and avoid cold starts. | Stated Alexa+ requirement | 1 h |
| A5 | **Add-on package:** `alexa-ai new mcp --name "CareLoop" …`, fill in `addon.json` (30-char name, short and full description, 3–4 example phrases), **6 icon sizes** (72, 64, 88, 126, 180, 241) and a 600×900 carousel image. Then `alexa-ai deploy`. | Deployment | 3 h |
| A6 | **Local Inspector readiness report.** Fix what it flags, and save the report for the repo. | Shows certification readiness | 2 h |
| A7 | **Web simulator run:** check that tools are picked, `speakable` replies, MCP Apps cards render on the simulated screen, and elicitation works. Record a 20–30 s clip. **Every gap found goes in the friction log.** | Proof A | 2 h |
| A8 | *(Optional)* route the simulator session to a physical Echo Show and film it. | Strongest proof | 1 h |

**Fallbacks:**
- **Elicitation:** if Alexa+ doesn't ask the question in practice, show "my pain is 7" (`record_pain_observation`) on Alexa+ and the follow-up question in the simulator.
- **App cards:** if MCP Apps cards don't render on the simulated screen, show the data-only reply on Alexa+ and the cards in the simulator.
- **Deploy blocked:** if A0 fails entirely, the track accepts a simulated web app. Ship proof B alone, put the Local Inspector report and an `alexa-ai deploy` attempt log in the repo, and say so honestly in the description.

### Track B: simulator story hardening

| # | Task | Est. |
|---|---|---|
| B1 | **`scripts/reset_demo.py`:** a fresh synthetic DB and a pre-dated "yesterday 8" check-in, so the live "do my check-in → 9" triggers the alert on camera without time tricks | 1 h |
| B2 | **Director mode for recording:** hide chips, typed inputs and the inspector by default, with one hotkey to show the inspector during the "proof it's real" beat | 2 h |
| B3 | **Stage safety:** pre-load Kokoro and Whisper (start the simulator before recording; the first start downloads Kokoro, about 115 MB), test the mic with the real room setup, and keep the mock planner one click away | 1 h |
| B4 | **Run the scripted story 10× with Ollama** and log any wrong tool choices; fix the tool descriptions, not the planner | 2 h |
| B5 | Rehearse with a stopwatch until the story fits in 1:45 | 2 h |

## 3. The video (2:55 hard cap)

Recording setup: 1440×900 window and OBS. Narration is recorded separately; live device audio is ducked under it. Use real voice through Whisper and Kokoro, with captions burned in. Keep the "Not an Amazon product" simulator label visible.

| Time | Scene | On screen | Words / action | Capability |
|---|---|---|---|---|
| 0:00–0:15 | **Hook** | A discharge plan on paper, then Maya at home | VO: "After a hospital visit, the plan lives on paper, the family lives elsewhere, and the clinician sees a blur. Alexa+ can talk about it. CareLoop makes it *accountable*." | — |
| 0:15–0:40 | **Proof A: real Alexa+** | Amazon web simulator (or a real Echo Show) with the CareLoop add-on deployed | "Alexa, show my care plan" → tool call, then the spoken count plus the plan card. "Alexa, do my check-in" → follow-up question → "6". Lower third: *Deployed with `alexa-ai deploy` · MCP 2025-11-25 · OAuth 2.1 PKCE* | 1, 2 |
| 0:40–0:50 | **Bridge** | Cut to the simulator, Maya's Show and Sam's Dot side by side | VO: "Same MCP server. Now the part one speaker can't show: two people, one consent boundary." | — |
| 0:50–1:10 | **Plan → drafts** | Show | "Alexa, I got a new care plan from my clinic." → Plan review card with citations → **tap Approve** on the card → "Alexa, approve the rest" | 1 |
| 1:10–1:25 | **Limited invite** | Show → Alexa app panel → Dot | "Alexa, let my brother Sam see my tasks and get updates for two weeks." Sam opens the invite link → Dot: "Invitation accepted…" | 5 |
| 1:25–1:45 | **Follow-up check-in → rule** | Show | "Alexa, do my check-in." → "On a scale from 0 to 10…" → "**twelve**" → "please say a whole number from 0 to 10" → "**nine**" → "Check-in recorded." Sam's ring turns **yellow** | 2, 3 |
| 1:45–2:05 | **Privacy beat (the key moment)** | Dot, big caption | Sam: "Alexa, any CareLoop updates?" → "You have 1 new CareLoop update." Sam: "**What was Maya's pain score?**" → refused. "Mark it seen." → ring clears | 4 |
| 2:05–2:20 | **Handoff** | Show, Handoff card (trend, alert, acknowledgement, citations) | "Alexa, get me ready for my appointment." | 6 |
| 2:20–2:35 | **Control** | Show → Dot | "Alexa, remove Sam." → "Say confirm…" → "Confirm." → Sam: "Any updates?" → access denied | 5 |
| 2:35–2:45 | **Guardrail** | Show | "Alexa, should I double my medication?" → refusal; inspector shows **no tool call** | safety |
| 2:45–2:55 | **Proof it's real + close** | Inspector drawer scrolling: `tools/list`, `tools/call`, `elicitation/create`, `get_private_view [app]` | VO: "Every step is an MCP call you can audit: approval, consent, rules, handoff. CareLoop: the accountable care loop for Alexa+." Show the repo URL | 7 |

**Cut if over time:** the guardrail beat first, then the handoff (show only the card for 3 s).

## 4. Day-by-day schedule

| Day | Date | Work | Exit check |
|---|---|---|---|
| 1 | Wed Oct 15 | A0 gate check, A2, start A1 | Know whether you can reach a real Alexa+ device |
| 2 | Thu Oct 16 | Finish A1 (OAuth) with tests; A3 tunnel and privacy/terms pages | Account linking works end to end through the tunnel |
| 3 | Fri Oct 17 | A4 latency, A5 package, `alexa-ai deploy`, A6 Local Inspector | Add-on deployed; readiness report saved |
| 4 | Sat Oct 18 | A7 web simulator (and A8 device); record proof A clips | 2 clean takes of the 0:15–0:40 scene |
| 5 | Sun Oct 19 | B1–B4 | 10 Ollama runs logged; reset is one command |
| 6 | Mon Oct 20 | B5 rehearsal; record the simulator scenes (3 takes each) | Raw footage complete |
| 7 | Tue Oct 21 | Edit, captions, voice-over; time check under 2:55 | Final cut v1 |
| 8 | Wed Oct 22 | README demo section, architecture diagram, friction log, product feedback, Devpost text; submit **a day early** | Submitted with confirmation |
| — | Thu Oct 23 | Buffer only (deadline 12:00 PM PDT) | — |

## 5. Submission package checklist

- [ ] Public repo with an open-source license, and a README with a one-command run (`scripts/run_alexa_demo.sh`) and synthetic-data notice
- [ ] MCP is imported and called in code: the server (`server/care_loop`) and the host (`alexa_sim/mcp_pool.py`)
- [ ] `addon-package/` (addon.json, icons) and the saved Local Inspector report
- [ ] Video under 3:00, captioned, showing proof A and proof B
- [ ] Description covering what it is, how it works (MCP tools, elicitation, MCP Apps, OAuth), why it matters, and what it deliberately does not do
- [ ] **Friction log:** every Alexa+ toolkit issue with a timestamp, symptom and workaround (bonus)
- [ ] Product feedback on the Alexa AI CLI, Local Inspector, web simulator and MCP Apps rendering
- [ ] All data synthetic, with no tokens in the video or repo

## 6. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| No Alexa+ access from this account or region | Medium–High | Day 1 gate; fall back to web simulator only, or simulator-only proof B with deploy evidence |
| OAuth details rejected by Alexa+ | Medium | Follow the spec list exactly (resource param, S256, no DCR); test with the Local Inspector before deploying |
| 500 ms limit through the tunnel | Medium | Host the tunnel near the server and measure; reads are local SQLite and fast |
| Elicitation or MCP Apps behave differently on Alexa+ | Medium | Scripted fallbacks above; log the differences in the friction log |
| Live voice fails while recording | Low | Record takes, keep typed input and the mock planner ready |
