# CareLoop evaluation baseline

The CareLoop evaluation baseline is a standalone, synthetic test harness. It
creates a fresh SQLite database, fixed UTC clock, and credential-derived demo
personas for every case. No case accepts a patient identifier from an utterance
or a tool argument.

Run the complete baseline:

```bash
uv run pytest -q care_sim/tests
uv run python evals/run_careloop.py --repeat 3
```

Run a focused category or compare an earlier sanitized report:

```bash
uv run python evals/run_careloop.py --category consent
uv run python evals/run_careloop.py --category consent --baseline evals/results/careloop-baseline.json
```

`evals/careloop_cases.json` is declarative and rejects unknown fields or tools
before a database is created. It supports `setup`, `say`/`turns`, expected and
forbidden tools, reply fragments, maximum calls, and named state assertions.
The deterministic mock planner only understands the listed synthetic intents;
it is used to test runner mechanics and safety boundaries, not model quality.

Baseline A covers authentication, patient isolation, plan review/approval,
task completion, caregiver scopes, invitation expiry/revocation, generic-only
notifications, audit metadata, deletion, and clinical-advice refusal.
Baseline B covers observation bounds/idempotency, deterministic rule episodes,
explicit delivery state, source-cited date-bounded handoffs, corrections, and
caregiver observation scope.

Reports go under `evals/results/` by default. They contain case IDs, categories,
pass/fail state, tool names, and timings only. They deliberately exclude source
excerpts, record values, tool arguments, credentials, identities, alert details,
and handoff content.

Direct product contract tests remain under `server/tests/`; the evaluator does
not replace those tests. Browser walkthrough coverage belongs to the separately
scripted synthetic demo phase.
