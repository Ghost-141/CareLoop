# CareLoop friction log

A running record of where building CareLoop for the Alexa+ track was harder than it should have been, what we saw, what caused it, how we got past it, and what would have helped. Entries are written when the problem happens, not reconstructed later.

**Project:** CareLoop, an MCP add-on for accountable care coordination, plus an Alexa+ behavior simulator (`alexa_sim`)
**Track:** Alexa+ (self-hosted MCP server over Streamable HTTP and a simulated Alexa+ web app)
**Environment:** macOS 26.5 on Apple Silicon (arm64), Python 3.13.15, `mcp` 2.1.1, FastAPI 0.143.1, Starlette 1.8.0, uvicorn 0.54.0, pydantic 2.14.1, kokoro-onnx 0.6.1, mlx-whisper 0.4.3, Ollama `qwen3.5:4b-mlx`
**Developer location:** Dhaka, Bangladesh (GMT+6). No Echo device and no Alexa+ developer access.

Severity: **Blocker** (stopped a goal), **High** (broke the build or demo until fixed), **Medium** (cost real time or forced a workaround), **Low** (papercut).
Status: **Resolved**, **Workaround** (we went around it), **Open** (still a problem).

## Summary

| ID | Area | Severity | Status | One line |
|---|---|---|---|---|
| F-01 | Alexa+ access | Blocker | Open | No clear way to get Alexa+ add-on Private Preview access, and no stated eligibility or regions |
| F-02 | Alexa+ testing | High | Workaround | Without a device or preview access, there was no way to test against real Alexa+, so we built a simulator |
| F-03 | Alexa+ docs, MCP Apps | Medium | Workaround | Unclear whether `resourceUri` belongs on the tool definition or in the tool response |
| F-04 | Alexa+ docs, notifications | Medium | Workaround | No documented way for an add-on to notify a caregiver; we had to simulate push |
| F-05 | Alexa+ docs, elicitation | Medium | Workaround | Elicitation support is documented only on the category add-on page |
| F-06 | Alexa+ auth | Medium | Resolved | A 401 must omit `WWW-Authenticate`, which differs from the standard MCP auth flow |
| F-07 | Alexa+ requirements | Medium | Open | The 500 ms round-trip rule is unclear for tools that wait on an elicitation answer |
| F-08 | Alexa+ policy | Medium | Resolved | No reference pattern for handling sensitive data on shared voice devices |
| F-09 | MCP Python SDK 2.x | High | Resolved | snake_case result fields silently read as empty; the simulator spoke generic replies and crashed |
| F-10 | MCP Python SDK 2.x | High | Resolved | `ToolAnnotations` is a model, not a dict; every voice turn returned HTTP 500 |
| F-11 | MCP client + anyio | High | Resolved | "Attempted to exit cancel scope in a different task" when unlinking an account |
| F-12 | MCP Python SDK 2.x | Medium | Resolved | Static resources can't receive `Context`, so `ui://` views couldn't authenticate the caller |
| F-13 | MCP Python SDK 2.x | Medium | Resolved | Tools returning plain `dict` produce no `structuredContent` |
| F-14 | MCP client sessions | Medium | Resolved | Queued session requests deadlocked when a tool waited on an elicitation |
| F-15 | uvicorn | Medium | Resolved | WebSocket returned 404 because no WebSocket library was installed |
| F-16 | Voice-safe design | High | Resolved | Hiding all record data from tool results made action tools unusable (no IDs) |
| F-17 | Voice-safe design | High | Resolved | Failures returned as successes, so the assistant could say "done" when nothing happened |
| F-18 | Local LLM planner | Medium | Resolved | The small model copied the add-on's follow-up question instead of calling the tool |
| F-19 | Caregiver notifications | Medium | Resolved | Acknowledged alerts kept the caregiver's ring lit |
| F-20 | Local speech | Low | Resolved | Kokoro's first run downloads about 115 MB; Whisper writes "Seven" as "7." |
| F-21 | Alexa+ add-ons, files | Medium | Workaround | No documented way for Alexa+ to pass a user's uploaded file to an add-on |
| F-22 | Alexa+ policy, dosage | Medium | Open | Unclear whether storing a prescriber's own instruction counts as "drug dosage content" |
| F-23 | Document intake | Medium | Resolved | Small local models mislabelled the pain rule and frequencies; a fixed-pattern safety net was needed |
| F-25 | Local LLM planner | Medium | Resolved | A 4B model picked the wrong task ID in multi-turn chats; tools now accept names, and gemma4 replaced qwen as planner |
| F-26 | Local LLM planner | High | Resolved | The model invented plan text, a past expiry date, and extra permissions; the server now refuses or reads back |
| F-27 | Alexa+ policy | Medium | Resolved | Policy requirements (disclosure before first use, crisis redirect, privacy/terms URLs) had to be built as product features |
| F-24 | PDF/OCR tooling | Low | Resolved | `pypdf` can't render pages for OCR; PaddleOCR's first run downloads models; storage rejects floats |

---

## Alexa+ platform and documentation

### F-01: No clear path to Alexa+ add-on access · Blocker · Open
- **Doing:** planning to deploy the CareLoop MCP server as a real Alexa+ add-on for the demo.
- **Expected:** a sign-up link, eligibility rules and an approval timeline.
- **Got:** the "Development Stages" page says only *"you request access to the Private Preview."* It doesn't say where, how long approval takes, or which countries qualify. The hackathon announcement offers templates, office hours and Discord, but doesn't say whether entrants get preview access.
- **Impact:** we couldn't plan a real-device demo with 8 days left. Alexa+ is US-centric, and we're in Bangladesh with no Echo device.
- **Workaround:** built the simulated Alexa+ web app that the track explicitly allows (F-02), and kept the server ready to deploy.
- **Suggestion:** link a preview request form from the toolkit overview and the hackathon resources, state supported regions, and give hackathon entrants a fast lane or a hosted web simulator account.

### F-02: No way to test against real Alexa+ · High · Workaround
- **Doing:** checking that tool selection, spoken replies and screen cards behave the way Alexa+ would.
- **Got:** the web simulator, Local Inspector and `alexa-ai` CLI all appear to need preview credentials, so we had no Amazon-provided way to see real Alexa+ behavior.
- **Workaround:** built `alexa_sim`, a host that copies the documented behaviors:
  - It finds tools through `tools/list` (no hardcoded intents) and speaks only from tool results.
  - It renders MCP Apps views in a sandboxed iframe and supports elicitation.
  - It confirms destructive tools and uses a separate caregiver account.
  - A live end-to-end test runs it against the real server.
- **Suggestion:** a public, credential-free version of the Local Inspector (even text-only) would let anyone check an MCP server against Alexa+ expectations before getting access.

### F-03: Where does `resourceUri` go? · Medium · Workaround
- **Doing:** adding MCP Apps screens (plan review, care circle, handoff).
- **Got:** two different statements. The Alexa+ docs say UI renders *"as long as you have resourceUri defined in the tool response."* The MCP Apps extension puts it on the **tool definition** as `_meta.ui.resourceUri`. Our first version put it in the result body, which a spec-compliant host would ignore.
- **Resolution:** the server now declares `_meta.ui.resourceUri` on every tool **and** returns the view link in the result. The simulator reads the definition first.
- **Suggestion:** show one complete example of an Alexa+ tool definition and its tool result with MCP Apps, and state which field Alexa+ reads.

### F-04: No documented way to notify a caregiver · Medium · Workaround
- **Doing:** showing that a caregiver's device lights up when a care rule triggers.
- **Got:** the MCP Toolkit docs mention "proactive discovery" (Alexa suggesting an add-on), but nothing on an add-on sending a notification to a user.
- **Workaround:** the simulator checks the caregiver's notifications after each turn and lights the Echo Dot ring. The UI and the docs label this "simulated push."
- **Suggestion:** document whether MCP add-ons can trigger notifications and how. If they can't, say so, and give a recommended pattern for time-sensitive care updates.

### F-05: Is elicitation supported for MCP add-ons? · Medium · Workaround
- **Doing:** making the daily check-in ask its own follow-up question ("what's your pain score from 0 to 10?").
- **Got:** elicitation appears only on the **category** add-on lifecycle page (*"uses the existing elicitation framework through the MCP protocol"*), not in the general MCP Toolkit pages. So we couldn't tell whether a general MCP add-on gets it, or how the question is presented by voice.
- **Workaround:** built `start_daily_checkin` with standard MCP elicitation, and made the simulator speak the question and keep the mic open. The rest of the tools still work for a client without elicitation (`record_pain_observation` takes the value directly).
- **Suggestion:** state elicitation support in the toolkit's supported-capabilities list. Describe how Alexa+ voices the question, which schema types it supports, and whether the timeout differs from F-07.

### F-06: 401 must omit `WWW-Authenticate` · Medium · Resolved
- **Doing:** checking the server against the QuickStart auth rules.
- **Got:** Alexa+ says to return `401` **without** `WWW-Authenticate` (*"not yet supported"*). The MCP authorization spec uses that header to point clients to the resource metadata. Our server sends `WWW-Authenticate: Bearer realm="careloop"` (`server/care_loop/auth.py`).
- **Resolution:** removed from the `/mcp` 401 in `BearerAuthMiddleware`, with a test that checks the header is absent. This is an easy-to-miss difference for anyone following the MCP spec.
- **Suggestion:** list every difference from the MCP auth spec in one table (no `WWW-Authenticate`, no Dynamic Client Registration, no Client ID Metadata Documents, no step-up), and have the Local Inspector flag each one.

### F-07: 500 ms rule vs a tool waiting on an answer · Medium · Open
- **Doing:** designing `start_daily_checkin`, which waits for the person's spoken answer mid-call.
- **Got:** the QuickStart says *"Responses must complete in under 500 ms round-trip."* A tool that is waiting on an elicitation answer can't meet that.
- **Status:** unresolved. All our other tools respond in milliseconds (local SQLite), but the check-in tool waits for the person.
- **Suggestion:** clarify whether the 500 ms limit covers time spent waiting for the user, or only server processing time.

### F-08: No reference pattern for sensitive data on shared devices · Medium · Resolved
- **Doing:** turning the policy rules ("don't collect or recite private personal information by voice", health disclaimers) into a design.
- **Got:** the policies say what not to do, but give no pattern for an add-on that holds health data and is used from a shared speaker.
- **Resolution:** designed CareLoop's voice-safe result:
  - **`speakable`:** counts and statuses only, safe to say aloud.
  - **`refs`:** opaque IDs with labels like "draft task 1", so the assistant can act on an item without seeing it.
  - **App-only data tool:** private detail reaches only a sandboxed MCP Apps view, through a tool hidden from the model.
  - **Tests:** check that nothing private ever lands in a spoken reply.
- **Suggestion:** publish a sample "sensitive data" add-on or design note covering what to speak, what to show, and what to keep off shared devices.

## MCP Python SDK and runtime

### F-09: SDK 2.x snake_case fields silently read as empty · High · Resolved
- **Got:** the simulator read `result.structuredContent`, `tool.inputSchema` and `result.isError`. In `mcp` 2.1.1 these are `structured_content`, `input_schema` and `is_error`. `getattr(..., default)` hid the mismatch, so the results were:
  - every reply was the generic fallback;
  - every tool appeared to have an empty schema;
  - errors were never detected.
- **Why tests missed it:** the unit tests used plain dicts, not SDK objects.
- **Resolution:** one conversion layer (`alexa_sim/mcp_pool.py: normalize_tool`, `normalize_result`) turns SDK objects into plain JSON-shaped dicts. A live end-to-end test now runs against a real server process.
- **Suggestion (upstream):** mention the rename in the 2.x migration notes. Accepting the camelCase names with a deprecation warning would have caught this immediately.

### F-10: `ToolAnnotations` is a model, not a dict · High · Resolved
- **Got:** `AttributeError: 'ToolAnnotations' object has no attribute 'get'`. Every voice turn returned HTTP 500 as soon as the server added annotations (`destructiveHint`, `readOnlyHint`).
- **Resolution:** annotations are converted with `model_dump(by_alias=True, exclude_none=True)` in the same conversion layer.

### F-11: Cancel scope exited in a different task · High · Resolved
- **Got:** `RuntimeError: Attempted to exit cancel scope in a different task than it was entered in` when unlinking an account. The MCP session was opened in one HTTP request and closed in another.
- **Resolution:** each linked account owns one long-lived worker task that opens and closes its MCP session. Requests reach it through a queue.
- **Suggestion (upstream):** an example of a long-lived, shared `ClientSession` in a web server (the normal host pattern) would prevent this.

### F-12: Static resources can't receive `Context` · Medium · Resolved
- **Got:** `ValueError: Resource 'ui://x/a' has no URI template variables, but the handler declares a Context parameter.` So a fixed `ui://careloop/plan-review` resource couldn't check who was asking.
- **Resolution:** this pushed us to the MCP Apps pattern anyway. Each `ui://` resource is a static HTML page with no data in it. After the handshake, the page loads private detail through an app-only tool (`get_private_view`), which applies the normal identity and consent checks.

### F-13: Plain `dict` returns produce no `structuredContent` · Medium · Resolved
- **Got:** tools annotated `-> dict` returned only JSON text, so hosts had no structured fields to read.
- **Resolution:** a typed `VoiceResult` result model. The SDK now publishes an output schema and returns `structuredContent`.

### F-14: Queued requests deadlocked during elicitation · Medium · Resolved
- **Got:** with requests handled one at a time per session, a tool waiting on an elicitation answer blocked every other call on that account, including the screen view's data requests.
- **Resolution:** the session worker runs each request as its own task on the shared `ClientSession`.

### F-15: WebSocket 404 under plain uvicorn · Medium · Resolved
- **Got:** `WARNING: No supported WebSocket library detected` and HTTP 404 on `/ws`, so the inspector and device states never updated live.
- **Resolution:** added an `alexa-sim` extra with `websockets`, plus a 4-second polling fallback in the page.

## CareLoop design problems we caused and fixed

### F-16: Voice-safe results hid the IDs action tools need · High · Resolved
- **Got:** the first privacy pass removed every record ID from tool results. `approve_plan_item`, `revoke_caregiver` and `acknowledge_alert` all need an ID, so nothing could be approved, revoked or acknowledged by voice.
- **Resolution:** `refs` carry opaque IDs with position-based labels ("draft task 1"), never record content.

### F-17: Failures reported as success · High · Resolved
- **Got:** a catch-all wrapper turned errors into normal results, so deleting a missing record said "request completed."
- **Resolution:** expected failures raise a `ToolError` with generic text (`isError: true`). A delete or revoke that matched nothing is now an error.

### F-18: Small local model copied the follow-up question · Medium · Resolved
- **Got:** with `qwen3.5:4b`, after a couple of check-ins the model answered "do my check-in" by **asking the pain question itself** in plain text, without calling the tool. Nothing would have been recorded.
- **Resolution:**
  - Questions from the add-on are kept out of the model's history.
  - History now includes the real tool calls and their voice-safe results.
  - A prompt rule says to call `start_daily_checkin` for check-ins.
  - Two repeat runs then used the real follow-up question every time.

### F-19: Acknowledged alerts stayed "action required" · Medium · Resolved
- **Got:** after Sam said "mark it seen," his ring stayed lit. The server listed acknowledged alerts as `action_required`.
- **Resolution:** notifications are now tracked per caregiver (`acknowledged` vs `action_required`), and only unacknowledged updates count. We also fixed an eval that had been asserting the old behavior.

### F-20: Local speech setup papercuts · Low · Resolved
- **Got:**
  - Kokoro's first start downloads about 115 MB of model files, which took about 2 minutes.
  - Whisper writes "Seven" as "7."
  - Browser speech recognition behaves differently from one browser to another.
- **Resolution:**
  - Both models load at startup, and the page shows which engines are active.
  - The answer parser accepts digits and number words.
  - The page falls back to browser speech if a local engine is unavailable.
- **Measured:** Kokoro takes 0.12–0.42 s per sentence and Whisper 0.12–0.28 s per utterance on Apple Silicon. Whisper transcribed all four test phrases exactly; "Seven" came back as "7."

### F-21: No documented file hand-off to add-ons · Medium · Workaround
- **Doing:** letting a patient give CareLoop their prescription through Alexa+.
- **Got:** Alexa+ accepts uploaded documents and photos for its own memory, but the MCP Toolkit docs describe no way to pass that file to an add-on. The `/mcp` endpoint also caps requests at 64 KB.
- **Workaround:** uploads go to CareLoop's own private view (`POST /api/care/documents/upload`), which the simulator's Alexa app panel calls. Voice picks up from there ("is my document ready?").
- **Suggestion:** a consented "share this file with an add-on" flow, or an MCP resource handle for user-shared files.

### F-22: Is a stored prescription "drug dosage content"? · Medium · Open
- **Got:** the policy says *"Drug dosage content requires documented developer affiliation with the manufacturer."* CareLoop never gives dosage information. It only stores the prescriber's own instruction, verbatim, for the patient's own record, and never speaks it on a speaker.
- **Question:** does a patient's own transcribed prescription fall under that rule?

### F-23: Small local models need a deterministic safety net · Medium · Resolved
- **Got:** in the first live runs, both `qwen3.5:4b` and `gemma4:e4b` labelled "Contact the clinic if your pain score is 7 or higher for 2 consecutive days" as a warning sign, not a rule. `qwen` also marked daily tasks as "every N hours".
- **Got (our bug):** the frequency table missed "three times **daily**", which would have suggested a single dose time. The model's disagreement flag exposed it.
- **Resolution:** a fixed-pattern recogniser for the rule's own wording takes its numbers from the text. The frequency table was fixed and is covered by tests. An eval runner (`evals/intake/run_intake.py`) now gates recall, invented numbers and injection, 3 runs per document.

### F-24: PDF and OCR tooling papercuts · Low · Resolved
- **Got:**
  - `pypdf` extracts text but cannot render a page to an image, so OCR needed `pypdfium2` as well.
  - PaddleOCR's first run downloads its models, about 1.5 minutes in our run.
  - CareLoop's storage rejects floats, so OCR confidence is stored as an integer percent.
- **Measured:** PaddleOCR read the synthetic scan and photo exactly, with 99–100% line confidence, about 8 s per page after the models are cached.

### F-25: Small planner models mis-pick IDs across turns · Medium · Resolved
- **Got:** in multi-turn runs, `qwen3.5:4b` answered "Sam handles the dressing" by passing the ID of a different task from an earlier result ("Sam will handle Take a short walk"). This happened in 2 of 3 runs. `gemma4:e4b` first asked about optional details (an expiry date) instead of acting.
- **Resolution:**
  - `assign_task` and `update_task_time` take `task` and `assignee` by **name or ID**; the server matches names exactly and refuses ambiguous ones.
  - The prompt says to pass names, and not to ask about optional details.
  - `gemma4:e4b-mlx` is now the recommended planner: right task in 3 of 3 runs.
- **Takeaway for Alexa+ add-ons:** let tools accept the user's own words for things, and have the server resolve them unambiguously. Opaque IDs passed through a model across turns are fragile.

### F-26: The planner model invents inputs · High · Resolved
- **Got** (a live demo session, logged in the simulator trace):
  - "I got a new care plan from my clinic" became `import_care_plan_text` with invented text ("User's new care plan text from their clinic visit").
  - "for two weeks" became `expires_at` = Jan 1, 2025, a date in the past, because the model didn't know today's date. The invitation was refused, so Sam never got access.
  - Sam's later requests said only "…unavailable", which hid the real reason.
  - `gemma4:e4b` also granted 7 permissions for "see my tasks and get updates".
- **Resolution:**
  - Import refuses text with no plan instructions, and the model is told to ask for the document instead.
  - The planner gets today's date; invitations take `expires_in_days`; a past date gets a clear error.
  - A family member with no current access is told so, and pointed to the invitation link. Missing a single permission still gets the generic refusal.
  - **`invite_caregiver` reads the exact permissions back** ("Sam will be able to see your tasks and get update alerts, for 14 days. Is that right?") and creates nothing without a yes. The tool description maps phrases to permissions; gemma4 then granted the right 2 permissions in 3 of 3 runs.
- **Takeaway:** consent must never depend on the model getting it right. Read it back and require a yes.

### F-27: Turning policy text into features · Medium · Resolved
- **Got:** the policy says add-ons must disclose data use *before* first interaction ("one-time permission prompt"), must redirect crisis references to emergency services or hotlines, and must list privacy-policy and terms URLs. None of these has an MCP-level mechanism or example.
- **Resolution:**
  - **Consent:** a server-side consent gate returns the disclosure as an offer (`next_step` → `accept_data_use`, with `retry`), so the host asks "Is that okay?" and then completes the original request.
  - **Crisis:** a deterministic crisis check runs in the host before any model sees the words, and in the question tool so nothing is filed away.
  - **Pages:** `/privacy` and `/terms` describe what this server actually stores, and for how long.
- **Suggestion:** a toolkit pattern for "first-use consent" and a standard crisis-handling hook would save every health add-on from reinventing them.

---

## Open questions for the Alexa+ team

1. How do hackathon entrants, and developers outside the US, get add-on Private Preview access? (F-01)
2. Which field does Alexa+ read for MCP Apps: `_meta.ui.resourceUri` on the tool, or the tool response? (F-03)
3. Can an MCP add-on send a notification to a linked user? (F-04)
4. Do general MCP add-ons support elicitation, and how is the question presented by voice? (F-05)
5. Does the 500 ms limit include time spent waiting on an elicitation answer? (F-07)
6. Does Alexa+ honor MCP Apps `visibility: ["app"]` (tools hidden from the model)? CareLoop relies on it to keep private view data away from the model.
7. Can a user hand a file they shared with Alexa+ to an add-on, with consent? (F-21)
8. Does a patient's own transcribed prescription count as "drug dosage content"? (F-22)

## Adding a new entry

Write it when it happens, and copy the exact error text.

```markdown
### F-NN: <short title> · <Blocker|High|Medium|Low> · <Resolved|Workaround|Open>
- **Doing:** what we were trying to do, and the tool or doc involved (with link)
- **Expected:** what the docs or tool suggested would happen
- **Got:** what actually happened, with exact error text or quote
- **Impact:** what it blocked or cost
- **Resolution / Workaround:** what we changed (file paths), or "none yet"
- **Suggestion:** one concrete change that would have prevented it
```

Then add a row to the summary table.
