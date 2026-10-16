# CareLoop × Alexa+ hackathon roadmap

Goal for the Amazon Developer Hackathon 2026 (Alexa+ track): make CareLoop add capabilities that Alexa+ does not already have, rather than rebuild what it does natively. Alexa+ handles conversation, reminders, memory, and rendering. CareLoop is the **system of record** behind it: what was approved, who can see it, what a rule decided, and what goes to the clinician.

## 1. Current state

### MCP tools registered today (`server/care_loop/tools/records.py`)

`list_care_tasks`, `record_task_completion`, `get_care_plan_source`, `list_care_records`, `search_care_history`, `record_pain_observation`, `correct_pain_observation`, `create_visit_handoff`, `export_care_data`, `delete_care_record`.

### Available only in the portal (`/care` REST), not over MCP

Plan intake (text/PDF), approve plan item, invite/accept/revoke caregiver, list grants, notifications, acknowledge alert.

### Gaps that block a real Alexa+ add-on

| Gap | Where | Why it matters |
| --- | --- | --- |
| Static bearer tokens only | `auth.py` | Alexa+ account linking needs OAuth 2.1 (authorization code + PKCE). |
| No MCP Apps UI resources | `ui/__init__.py` is empty | Without a `resourceUri`, Alexa+ falls back to data-only responses. On an Echo Show, the plan review, chart, and handoff are your strongest visuals. |
| Notification/ack tools missing from MCP | README lists `list_generic_notifications` / `acknowledge_alert`, but `records.py` does not register them | The caregiver half of the story isn't reachable by voice. Doc/code mismatch. |
| One observation type, one rule type | `core.py` (`pain_score`, `PAIN_SCORE_AT_OR_ABOVE`) | Too narrow for a compelling demo. |
| Epoch-int dates in tool args | `create_visit_handoff(from_date: int, …)` | LLM clients do much better with ISO dates or "last 7 days" style ranges. |
| No speak-safe vs private split in tool output | all tools | Alexa+ may read private detail aloud on a shared speaker, which policy prohibits. |
| Rate limit is configured but not enforced | `config.py` | Should be enforced on a public endpoint. |
| Not deployed | — | Alexa+ needs a public HTTPS `/mcp`. |

## 2. Overlap with Alexa+ and what to do about it

| CareLoop today | Alexa+ / Alexa already does | Decision |
| --- | --- | --- |
| Task list + completion | Reminders, to-dos, medication reminders, Care Hub | **Don't compete.** Keep tasks only as *approved, source-cited plan items*. Return `reminder_suggestions` so Alexa+ creates the reminders with its own native feature. |
| Plan document intake | Alexa+ accepts uploaded/emailed documents and recalls them | **Differentiate.** Alexa+ *remembers* documents; CareLoop *requires approval* of each item and keeps the citation. Add plan versioning and diffs (F6). |
| `search_care_history` | Alexa+ memory recall | Keep it, but frame as an "attributable record lookup" with source and actor, not general recall. |
| Caregiver alerts | Care Hub / Alexa Together activity alerts, fall detection | **Differentiate.** Those are activity alerts. CareLoop alerts are *plan-rule episodes* with scoped, revocable consent and an audit trail. |
| Old voice simulator (`care_sim/`, since removed) + Ollama intent router | Alexa+ NLU and response generation | **Retire from the demo path.** Only its offline eval harness was kept, now in `alexa_sim/evaluator/`. Alexa+ is the voice layer. |
| Pain-score logging | Nothing structured | Keep and generalize (F2). |

**Positioning line:** *"Alexa+ remembers. CareLoop proves: who approved it, who saw it, what triggered, and what the doctor gets."*

## 3. New features that extend Alexa+

Ranked by demo impact per hour of work. P0 = needed for submission. P1 = strong differentiators. P2 = stretch.

### P0: platform fit

**F0. OAuth 2.1 account linking.** Add `/oauth/authorize`, `/oauth/token`, and discovery metadata (`/.well-known/oauth-authorization-server`, protected-resource metadata) using authorization code + PKCE. Map the token to `Identity(patient|caregiver)`. Keep the static token for local tests. Files: `auth.py`, new `oauth.py`, `server.py`.

**F1. Voice-safe output contract.** Every tool returns:
```json
{ "speakable": "You have 2 plan tasks today.",
  "private": { ... full detail ... },
  "surface": "glance|private_screen",
  "ui": { "resourceUri": "ui://careloop/..." } }
```
The server `INSTRUCTIONS` tell Alexa+ to speak only `speakable`. Sensitive tools (source excerpt, observations, handoff) return the detail only to the MCP App view. This is the core privacy idea, and it is new to Alexa+. Add an eval category that checks no private field leaks into `speakable`.

**F2. MCP Apps widgets (Echo Show / alexa.com).** Register `ui://` resources and return them from tools:
- **Plan Review card:** draft items beside their source citations, with Approve/Reject buttons (calls `approve_plan_item` through the host bridge).
- **Check-in trend card:** observations over time with the rule threshold line. Facts only, no interpretation.
- **Handoff card:** the visit summary, with a "share with clinician" action (F7).
- **Care Circle card:** who has which scopes and when each expires, with revoke.
Follow the sandbox rules in the layout guide: no cookies, no localStorage, host bridge only.

**F3. Expose the missing workflows over MCP.** `import_care_plan_text`, `approve_plan_item`, `list_care_circle`, `invite_caregiver`, `revoke_caregiver`, `list_generic_notifications`, `acknowledge_alert`. Accept ISO dates and relative ranges (`"last_7_days"`).

**F4. Deploy.** Run a container on AWS (App Runner or ECS Fargate) with HTTPS. SQLite on a mounted volume is fine for a demo. Validate with the Alexa+ Local Inspector, then `alexa-ai deploy`, then test on a real device.

### P1: what Alexa+ can't do natively

**F5. Plan-driven structured check-in (MCP elicitation).** `start_daily_checkin` reads the *approved* plan and uses MCP elicitation to ask only the questions the plan defines (for example pain 0–10, "did you complete the walk?", sleep hours). Alexa+ keeps the conversation natural, and CareLoop guarantees the answers are structured, validated, idempotent, and attributable. Generalize the observation schema: `observation_type ∈ {pain_score, sleep_hours, mood_1_5, fluid_cups, steps_band}`, each with a fixed validator.

**F6. Plan versioning and change reconciliation.** When a new plan is uploaded, compute a diff against the active plan: added, removed, and changed items with citations. Changed items need re-approval, and superseded items are retired with history kept. Voice: *"Your new plan changes 2 items. Review them on your screen."* Alexa+ document memory can't tell you that instruction #3 changed since last week.

**F7. Clinician share link (time-boxed, read-only).** `share_handoff_with_clinician(expires_in_hours)` creates a single-purpose grant with a signed URL. It is logged, revocable, and automatically expires. It closes the loop to the visit.

**F8. "Questions for my doctor" queue.** *(Implemented: `add_question_for_clinician`.)* *"Alexa, add a question for my doctor: can I start swimming?"* is stored attributed and timestamped, then included in the next handoff. Simple, very demoable, and it stays out of medical advice because CareLoop never answers the question.

**F9. Access transparency / consent receipts.** *(Implemented: `who_accessed_my_care_data`.)* `who_accessed_my_care_data(range)` reads the existing `audit()` log: *"This week Sam viewed your tasks twice and acknowledged one update."* Consent you can audit by voice is new to Alexa+.

**F10. More deterministic rule types.** Add `AT_OR_BELOW`, `MISSED_TASK_N_DAYS`, and `NO_CHECKIN_BY_LOCAL_TIME`. They still need source backing and patient approval. The "no check-in" rule is the plan-derived version of Alexa's "first interaction" alert.

### P2: stretch

**F11. Care-circle task claiming.** Support tasks such as "pick up prescription" can be claimed by a caregiver who has `claim_tasks` scope: *"Alexa, tell CareLoop I'll cover Thursday's pickup."* The patient sees who is covering and where the gaps are. Coordination across several people is something Alexa+ doesn't do.

**F12. MCP prompts.** Publish `weekly_review` and `pre_visit_prep` prompts that chain handoff + questions + trend card.

**F13. Reminder hand-off to Alexa+.** *(Implemented: `reminders` in task results, plus family assignment with `assign_task`.)* Tool results include `reminder_suggestions[]` (title, schedule, source citation) so Alexa+ creates native reminders. CareLoop never schedules them itself.

## 4. Revised demo story (≈3 min)

1. **Echo Show:** "Alexa, I got my discharge plan." Maya emails the plan. The Plan Review card (F2) shows 3 drafts with citations, and she approves on screen.
2. "Alexa, add my brother Sam to my care circle, tasks and alerts only." The Care Circle card shows the scopes and expiry (F3).
3. **Day 2 and 3:** "Alexa, do my check-in." A plan-driven elicitation (F5) asks for pain, walk, and sleep. The second high score triggers a rule episode.
4. Sam's device hears only "CareLoop update available." He acknowledges it, and nothing private is spoken (F1).
5. "Alexa, add a question for my doctor…" (F8)
6. A new plan arrives. "2 items changed, review on screen." (F6)
7. "Alexa, prepare for my appointment." The Handoff card shows observations, the trend, and her questions, and she shares a 48-hour clinician link (F7).
8. "Who has seen my data this week?" (F9) Then she revokes Sam, and his next request is denied.

## 5. Execution order

| Step | Work | Est. |
| --- | --- | --- |
| 1 | F3 tool exposure + ISO dates; fix the README/tool mismatch | 0.5 day |
| 2 | F1 output contract + leak eval cases | 0.5 day |
| 3 | F0 OAuth 2.1 + PKCE | 1 day |
| 4 | F4 deploy + Local Inspector smoke test | 0.5 day |
| 5 | F2 MCP Apps: Plan Review + Handoff cards first | 1.5 days |
| 6 | F5 generalized observations + elicitation check-in | 1 day |
| 7 | F8 questions, F9 access log (small, reuse `audit`) | 0.5 day |
| 8 | F6 plan diff, F7 clinician link | 1 day |
| 9 | F10 rules, then P2 if time | remaining |
| 10 | Re-record E2E demo on a real device; update evals and README | 0.5 day |

## 6. Guardrails to keep (judging and policy)

- No diagnosis, dosage, or emergency claims. Health responses cite their source and include a professional-advice disclaimer.
- Never speak private content. Shared surfaces get only `speakable`.
- Synthetic data only in the demo. Label it on every card.
- Consent must be explicit, scoped, expiring, and revocable. It is never inferred from a voice or a shared device.

References: [MCP Toolkit overview](https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-overview.html) · [Supported capabilities](https://developer.amazon.com/docs/alexaplus/add-ons/category-sdk-mcp-supported-capabilities.html) · [Layout and rendering](https://developer.amazon.com/docs/alexaplus/add-ons/mcp-addon-layout-and-rendering.html) · [Authentication](https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-authentication.html) · [Policy requirements](https://developer.amazon.com/docs/alexaplus/add-ons/policy-requirements.html) · [Alexa+ features](https://www.aboutamazon.com/news/devices/new-alexa-top-features)
