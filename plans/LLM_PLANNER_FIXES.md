# Fixing the live-model planner failures (F-29 to F-32)

Source: `evals/run_llm_planner.py` with `gemma4:e4b-mlx`, 96 of 108 runs passed. Four scenarios failed every run. Details are in `docs/FRICTION_LOG.md`.

**Root cause:** the tool descriptions tell the model to do things the host already does ("Confirm with the patient first"), and two tools need values only the server can create (an idempotency key, an opaque record id). No change to the model is needed.

**Scope:** server tool descriptions and arguments, one planner prompt rule, new eval scenarios. No change to the held-confirmation flow in the simulator.

## Order of work

| Step | Fixes | Files | Est. |
| --- | --- | --- | --- |
| 1. Extend the eval first | all | `evals/run_llm_planner.py` | 30 min |
| 2. Destructive tool descriptions | F-30, F-31 | `server/care_loop/tools/records.py` | 20 min |
| 3. Revoke by caregiver name | F-30 | `records.py`, `core.py` | 40 min |
| 4. Readable record labels | F-31 | `records.py` | 30 min |
| 5. Optional idempotency key | F-29 | `records.py` | 20 min |
| 6. Planner prompt rule | F-32 | `alexa_sim/backend/alexa_sim/planners.py` | 15 min |
| 7. Rerun, update docs | all | eval, `docs/FRICTION_LOG.md` | 30 min |

About 3 hours. Do step 1 first so every fix is measured against a failing test.

## 1. Extend the eval (before any fix)

- **Seed a grant for Sam:** add a seed mode that creates an active caregiver grant by calling `invite_caregiver` as Maya, then `accept_caregiver_invitation` as Sam. This settles the caveat on F-30, where the test world had nothing to revoke.
- **Seed a pain record:** add a seed mode that records one check-in so deletion has a target.
- **New scenarios:**
  - `remove-caregiver-granted`: "Alexa, remove Sam" with the grant in place. Expect `list_care_circle` then `revoke_caregiver` held for confirmation, then "confirm" revokes it.
  - `delete-last-pain`: with one record. Expect `list_care_records` then `delete_care_record` held for confirmation.
  - `delete-then-confirm`: the same, then "confirm". Expect the record gone and the reply "Care record deleted."
  - `pain-words-high-valid`: "my pain is ten", "seven", "four". All must record.
- **Success rule for destructive tools:** a turn that holds a confirmation counts as success. A model-worded question does not.

## 2. Fix the destructive tool descriptions (F-30, F-31)

- **Change:** in `revoke_caregiver` and `delete_care_record`, remove "Confirm with the patient first."
- **New text:** "The host asks the person to confirm before this runs, so call it directly. Find the ref first with `list_care_circle` (or `list_care_records`); never ask the person for an id."
- **Why it works:** gemma follows tool descriptions closely. The old sentence is what made it ask its own question instead of calling the tool.
- **Check:** the original `remove-caregiver` and `delete-record` scenarios, which should now hold a confirmation.

## 3. Let `revoke_caregiver` take a name (F-30)

- **Change:** add an optional `caregiver` argument ("Sam"). Keep `invitation_id` for the app view and for model calls that use a ref.
- **Matching:** in the tool, resolve the name against the patient's grants by display name, ignoring case. If it matches more than one active grant, raise a generic error so the model asks which one. If it matches none, fail generically.
- **Pattern to copy:** `assign_task` and `update_task_time` already resolve names this way, and their scenarios pass.
- **Tests:** unit tests in `server/tests/` for a unique match, no match, and two grants with the same name.

## 4. Readable record labels (F-31)

- **Problem:** `list_care_records` labels refs "record 1", "record 2". The model can't tell which one is "my last pain record".
- **Change:** label by kind and recency, for example "latest pain check-in", "pain check-in 2", "care plan task 1". Keep the labels free of values and dates, so the voice-safe contract still holds.
- **Check:** confirm the order the service returns, so "latest" really is the newest. Add a test that the labels contain no digits from pain scores.

## 5. Make the idempotency key optional (F-29)

- **Change:** in `record_pain_observation` and `correct_pain_observation`, make `idempotency_key` optional and generate a random one on the server when it is missing.
- **Keep:** a supplied key still makes retries safe, and the server still rejects keys over 128 characters.
- **Prompt:** drop the "fresh unique idempotency_key" instruction from the planner prompt. Nothing should depend on the model producing one.
- **Tests:** a call without a key records once. A repeated call with the same key still returns the same record. Two calls without keys make two records.

## 6. Planner prompt rule for records (F-32)

- **Change:** add one line to `SYSTEM_PROMPT` in `alexa_sim/backend/alexa_sim/planners.py`: any question about the patient's records or scores must go through a CareLoop tool, and the model speaks only the tool's answer, never its own explanation.
- **Why:** the server already returns the generic "records are unavailable" line for a caregiver without a grant.
- **Check:** `caregiver-privacy` should call a tool and reply with the generic line, with no invented reasoning.

## 7. Verify and document

- **Run:** the four failing scenarios and the new ones with `--repeat 3`, then the full set to catch regressions. Use `gemma4:e4b-mlx` only.
- **Run:** the full pytest suite, since descriptions and arguments changed. The tool-title test and the stub signatures in `server/tests/` may need small updates.
- **Pass bar:** all four original failures pass 3 of 3, and no scenario that passed before now fails.
- **Docs:**
  - Mark F-29 to F-32 Resolved with the change and the result.
  - Update the pass count in F-33.
  - Update the Alexa+ roadmap note that the demo can use the real model for the revocation step.
- **Fallback:** if a scenario still fails after steps 2 to 6, record the remaining behavior in the friction log as Open and demo that step with the scripted planner.

## Risks

- **Tool descriptions are also read by the real Alexa+ model.** The new text is shorter and clearer, so it should help there too, but it can't be tested here.
- **Name matching on revoke:** two caregivers with the same name must never revoke the wrong person. The ambiguity error in step 3 covers this.
- **Optional key:** a retry without a key is no longer deduplicated. A duplicate check-in is harmless and visible, and the correction tool already preserves history.
