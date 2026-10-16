# Multi-turn workflows plan

> **Status (Oct 16, 2026): implemented and tested end to end.** The work went beyond this plan:
> - **Interruptions:** a new "Alexa, …" request pauses a waiting workflow.
> - **Clearer tool arguments:** `assign_task` / `update_task_time` take a task or person by **name** (`task`, `assignee`), because the small local model picked the wrong ID.
> - **Asking for a missing time:** "change the time" with no time asks "What time should it be?".
> - **Planner choice:** `gemma4:e4b-mlx` is now the recommended planner (right task in 3 of 3 runs, against 1 of 3 for `qwen3.5:4b-mlx`).

**Goal:** turn CareLoop from "one command, one answer" into conversations that carry a task across turns. CareLoop should ask its own next question, remember what "it" refers to, offer the natural next step, and resume where the person left off.

**Rule:** every safety boundary stays.
- Medicine and flagged items are still approved only on screen.
- Nothing private is spoken.
- Destructive actions still need "confirm".

## 1. What exists today

| Multi-turn piece | Limit |
|---|---|
| `start_daily_checkin` asks one elicitation question (pain) | Stops after one question |
| "Remove Sam" → "confirm" | A single yes/no |
| The planner model sees earlier turns and tool calls | Nothing leads the next step; "it" isn't resolved |

## 2. Building blocks

| # | Block | Where it lives | Why there |
|---|---|---|---|
| W1 | **Chained elicitation**: one tool asks several questions in a row | CareLoop server (MCP elicitation) | Standard MCP that Alexa+ supports; answers are validated by schema |
| W2 | **Saved workflow state**: a `WORKFLOW` record with kind, item list, position and status | CareLoop server | Survives across turns, devices and days ("continue my review") |
| W3 | **Next-step offers**: results may carry `next_step {say, tool, arguments}` | Server proposes, host asks | The server decides what is safe to offer; a plain "yes" runs it |
| W4 | **Reference memory**: the last task and person mentioned | Host (as Alexa+ does) | Resolves "move it to 8" and "give that one to Sam" |

## 3. Workflows to build

### A. Plan-driven daily check-in (W1)
`start_daily_checkin` asks:
1. **Pain score** (0–10, as today).
2. **Up to 3 of the patient's own tasks due today** that aren't recorded yet: "Did you do Short walk today?" (yes/no). A "yes" records the completion.
3. Tasks assigned to family members are **not** asked; the summary mentions them.

It ends with a summary that holds no values. Example: "Check-in recorded. You did 1 of 2 tasks; Change the dressing is still to do. Sam has Evening check-in at 19:00."

"Stop" or "cancel" keeps what was already answered.

```
Maya: Alexa, do my check-in.
Alexa: On a scale from 0 to 10, what's your pain score today?   → "six"
Alexa: Did you do Take a short walk today?                       → "yes"
Alexa: Did you do Change the dressing today?                     → "not yet"
Alexa: Check-in recorded. You did 1 of 2 tasks. Change the dressing is still to do.
```

### B. Guided voice review of draft items, with pause and resume (W1 + W2)
New tool **`review_plan_by_voice`**. It starts a `WORKFLOW` of kind `plan_review`, or resumes the active one.
- **Order:** pending drafts in document order.
- **Screen only:** medicine items and flagged items are skipped and counted.
- **Each item** is one elicitation. "Item 2 of 5: Change the dressing every evening, at 19:00. Approve, change the time, give it to someone, skip, or stop?" The fields are:
  - `action` ∈ {approve, change time, skip, stop}, optional
  - `new_time`: the spoken time, resolved by the server against the item's current time ("9" for an evening task means 21:00)
  - `who` ∈ {me, \<names of family members with perform_tasks\>}, for tasks only
- **What each answer does:**
  - a time → approve with that time;
  - a person → approve, then `assign_task`;
  - approve → approve;
  - skip → leave as a draft;
  - an empty or unclear answer → re-asked once;
  - stop, cancel or decline → **pause**, saving the place.
- **Pause reply:** "Okay, I've saved your place. 3 items left. Say 'continue my review' anytime."
- **End reply:** "Done: 3 approved, 1 skipped. 3 medicine items are waiting on your screen." This can also offer the next step (C).
- **Speaking item text:** the item's text may be spoken here, but only for patient-only, non-medicine items. The patient asked for the review on their own device, and these lines are already spoken as task names in reminders. Medicine text is never spoken.

```
Alexa: Your document is ready. 8 items need your approval… Want to go through them now?   (offer)
Maya: yes
Alexa: Item 1 of 5: Take a short walk every morning, at 08:00. Approve, change the time, give it to someone, skip, or stop?
Maya: make it 9
Alexa: Item 2 of 5: Change the dressing every evening, at 19:00. …
Maya: give it to Sam
Alexa: Item 3 of 5: Follow-up appointment on 2026-10-24 … Approve, skip, or stop?
Maya: stop
Alexa: Okay, I've saved your place. 3 items left. Say "continue my review" anytime.
(next day) Maya: Alexa, continue my review → picks up at item 3
```

### C. Next-step offers (W3)
`VoiceResult.next_step` (optional): `{say, tool, arguments}`. The server appends `say` to `speakable`. The host remembers the offer for one turn: "yes" runs that exact tool call, and "no" or anything else drops it. Destructive tools are never offered.

| After | Offer |
|---|---|
| `import_care_plan_text` / `get_intake_status` (ready, with voice-reviewable drafts) | "Want to go through them now?" → `review_plan_by_voice` |
| Review finished or item approved, an unassigned timed task exists, and a family member has `perform_tasks` | "Want Sam to handle Change the dressing?" → `assign_task` |
| `add_question_for_clinician` | none (avoids chains of questions) |

### D. "It" and "that one" (W4)
The host keeps `device.context = {task: {id, label, times}, person: {id, name}}`. It's updated from each turn's results (tasks in refs, people in care-circle refs, assignments). The context is passed to the planner:
- **Ollama:** a short system note listing the recently mentioned items with their IDs.
- **Mock:** fixed patterns, "move/change it … \<time\>" → `update_task_time`, and "give it/that one to him/Sam" → `assign_task`.

New server tool **`update_task_time(task_id, new_time)`**: patient only, active tasks only, resolved the same way as in B, recorded in the edit history.

## 4. Host changes
- **Answer parsing:**
  - yes/no words map to enum options (approve/skip);
  - "me"/"myself" maps to the `who` option for the patient;
  - fields named `*time` get the spoken time phrase;
  - optional fields may stay empty, and the server re-asks.
- **Offers:** `device.offer` (one turn): "yes" → call the offered tool → speak its result.
- **Reference memory:** `device.context` is updated after every turn; the planner signature gets `context`.
- **Listening:** the mic stays open after each review question (already true for elicitation).

## 5. Tests
- **Server unit tests:**
  - multi-question check-in (yes/no, completions recorded, stop mid-way keeps answers);
  - review workflow (approve, time change, assign, skip, stop then resume, medicine skipped, end summary and offer);
  - `update_task_time`;
  - `next_step` shapes.
- **Host unit tests:** offer accept and decline; context resolution; parser synonyms.
- **Live end to end** (real server and simulator): upload → offer → "yes" → review three items (time, assign, stop) → resume → finish → "move it to 8 pm" → multi-question check-in. Plus one run with the local Ollama planner.

## 6. Order and estimate
| Step | Work | Est. |
|---|---|---|
| 1 | Server: W1 check-in, `update_task_time`, `next_step` | 0.5 day |
| 2 | Server: W2 review workflow tool + `WORKFLOW` record | 0.5 day |
| 3 | Host: parser, offers, reference memory, mock/Ollama context | 0.5 day |
| 4 | Tests + live end to end + Ollama run | 0.5 day |

**Alexa+ note:** Alexa+ documents elicitation support. Whether its 500 ms response rule covers time spent waiting for the user is still open (friction F-07).
