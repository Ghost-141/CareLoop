#!/usr/bin/env python3
"""Seed a clearly labelled, synthetic CareLoop demo journey.

This never deletes or changes existing records. It is idempotent: after the
synthetic plan has been seeded once for a patient, a second run reports that
fact and makes no changes.

    uv run python scripts/seed_careloop_demo.py
    uv run python scripts/seed_careloop_demo.py --db /tmp/careloop-demo.db
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "server") not in sys.path:
    sys.path.insert(0, str(ROOT / "server"))

from care_loop.auth import Identity
from care_loop.config import Settings
from care_loop.core import CareLoopService
from care_loop.storage import CareLoopStorage

TITLE = "CareLoop fictional recovery-coordination plan — synthetic demo only"
SCENARIO = "Fictional adult recovery-coordination journey; not medical advice"
DAY = 86_400
PLAN = "\n".join((
    "TASK: Complete a morning mobility check-in | schedule: morning",
    "TASK: Review today's support plan | schedule: lunchtime",
    "TASK: Prepare questions for the next care-team visit | schedule: afternoon",
    "TASK: Confirm the next support reminder | schedule: evening",
    "RULE: PAIN_SCORE_AT_OR_ABOVE threshold=7 consecutive_days=2",
))


def seed(db_path: Path, patient_id: str) -> dict[str, int | bool]:
    """Create a compact, fully-approved synthetic story in one patient scope."""
    storage = CareLoopStorage(db_path)
    try:
        if any(row.get("title") == TITLE for row in storage.list(patient_id, "DOCUMENT")):
            return {"seeded": False, "tasks": 0, "observations": 0, "alerts": 0}

        patient = Identity(patient_id, "patient", patient_id, "synthetic-demo")
        service = CareLoopService(storage, storage.clock, retention_days=365)
        intake = service.intake_text_document(patient, TITLE, PLAN)
        drafts = intake["drafts"]
        for item in drafts:
            service.approve_plan_item(patient, item["id"])

        active_tasks = [row for row in service.list_care_tasks(patient) if row["type"] == "PLAN_TASK"]
        # Show believable progress: two items completed and two still active.
        # These are synthetic coordination events, not clinical instructions.
        for index, task in enumerate(active_tasks[:2], start=1):
            service.record_task_completion(patient, task["id"], completed_at=storage.clock() - index * 3_600)

        # A small change over four fictional daily check-ins reaches the one
        # explicitly approved threshold. It creates a generic caregiver update,
        # never a diagnosis, recommendation, or disclosed symptom narrative.
        now = int(storage.clock()) - 60
        observations = ((now - 3 * DAY, 2), (now - 2 * DAY, 4), (now - DAY, 7), (now, 8))
        for index, (when, score) in enumerate(observations, start=1):
            service.record_observation(patient, pain_score=score, observed_at=when,
                                       idempotency_key=f"careloop-demo-checkin-{index}")
        alerts = storage.list(patient_id, "ALERT")
        service.create_visit_handoff(patient, now - 2 * DAY, now)
        return {"seeded": True, "tasks": len(active_tasks), "observations": len(observations), "alerts": len(alerts)}
    finally:
        storage.close()


def main(argv: list[str] | None = None) -> int:
    settings = Settings.from_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path(settings.db_path), help="SQLite database to seed")
    parser.add_argument("--patient", default=settings.patient_id, help="synthetic patient identifier")
    args = parser.parse_args(argv)
    result = seed(args.db, args.patient)
    if not result["seeded"]:
        print("CareLoop synthetic demo data is already present; no records were changed.")
        return 0
    print("Seeded synthetic CareLoop demo data:")
    print(f"  scenario: {SCENARIO}")
    print(f"  approved tasks: {result['tasks']}")
    print(f"  synthetic check-ins: {result['observations']}")
    print(f"  generic action-required alerts: {result['alerts']}")
    print("No real patient information was created or imported.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
