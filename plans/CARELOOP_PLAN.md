# CareLoop implementation, evaluation, and demo plan

CareLoop is a standalone synthetic adult-care coordination project. It has its own repository, package namespace, credentials, database, simulator, tests, and CI. It has no runtime, storage, identity, compatibility, or test dependency on any other application.

The product loop is: reviewed source document → patient-approved tasks/rules → structured observations → deterministic rule evaluation → consent-scoped caregiver action → source-linked visit handoff.

## Completed foundation

- Patient-scoped SQLite/WAL storage, deletion, expiry, purge, and retrieval.
- Authenticated patient/caregiver roles, explicit invitation scopes, expiry, and immediate revocation.
- Safe text/PDF intake, draft review, source citations, task completion, and deterministic approved rules.
- Pain-score observations, idempotent writes, corrections, rule episodes, generic alerts, acknowledgement, and handoffs.
- Standalone evaluator with Baseline A/B cases and a synthetic E2E demo.

## Release work

1. Run all tests, evaluator repeats, and the E2E demo from a clean environment.
2. Build the full authenticated dashboard and browser-level synthetic demo.
3. Before a live integration, recheck applicable policy, identity, and privacy requirements. Never use real patient data in this prototype.
