"""Synthetic starting state for the recorded demo and for testers.

Maya came home from the clinic three days ago. She has already said yes to data use,
her brother Sam is in her care circle, and she has logged a pain score each day since,
the most recent one high. Her prescription is *not* loaded: sharing it, reviewing it,
and watching the approved rule fire on the next high score is the demo.

Everything here is fictional. Reset only ever touches the one demo patient.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from .auth import Identity
from .core import CareLoopService

SEED_TAG = "careloop-demo-seed-v1"
CAREGIVER_NAME = "Sam"
CAREGIVER_SCOPES = ["read_tasks", "perform_tasks", "receive_alerts", "acknowledge_alerts"]
# Pain scores for the days before today, oldest first. Yesterday's 7 means one more
# score of 7 or higher today meets the prescription's "2 consecutive days" rule.
PAIN_HISTORY = (3, 4, 7)
QUESTION = "When can I go back to work?"


def is_seeded(service: CareLoopService, patient: str) -> bool:
    return service.profile(patient).get("demo_seed") == SEED_TAG


def has_records(service: CareLoopService, patient: str) -> bool:
    return bool(service.storage.list(patient))


def seed_demo(service: CareLoopService, patient: str, caregiver_id: str) -> dict[str, Any]:
    """Create the starting state in an empty patient scope. Returns a short summary."""
    maya = Identity(patient, "patient", patient, "demo-seed")
    sam = Identity(caregiver_id, "caregiver", patient, "demo-seed")
    service.accept_data_use(maya)
    service.update_profile(maya, name=service.default_patient_name)
    profile = service.profile(patient) | {"demo_seed": SEED_TAG}
    service.storage.put(patient, "profile", "PATIENT", profile)

    invitation = service.invite(maya, CAREGIVER_SCOPES, name=CAREGIVER_NAME)
    service.accept_invitation(sam, invitation["id"])

    # One check-in per day at noon UTC (rules count UTC calendar days).
    today = datetime.fromtimestamp(service._now(), UTC).date()
    for days_ago, score in zip(range(len(PAIN_HISTORY), 0, -1), PAIN_HISTORY):
        day = today - timedelta(days=days_ago)
        at = int(datetime(day.year, day.month, day.day, 12, tzinfo=UTC).timestamp())
        service.record_observation(maya, pain_score=score, observed_at=at, idempotency_key=f"demo-seed-{day}")
    service.add_clinician_question(maya, QUESTION)
    return {"patient_name": service.patient_name(patient), "care_circle": [CAREGIVER_NAME],
            "pain_history": list(PAIN_HISTORY), "questions": 1, "plan_loaded": False}


def reset_demo(service: CareLoopService, patient: str, caregiver_id: str) -> dict[str, Any]:
    """Delete every record of the demo patient, then seed the starting state again."""
    service.storage.wipe_patient(patient)
    return seed_demo(service, patient, caregiver_id)
