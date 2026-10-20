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


# ---- "Day four at home": three days of history for suggestions, teach-back and the handoff -----------------
STORIES = ("first-visit", "history")
# The typed sample prescription, line for line. Its two dates follow the day of the reset.
LINES = {
    "p1:L1": "Riverside Family Clinic - SYNTHETIC DEMO DOCUMENT",
    "p1:L2": "Patient: Maya Demo Date: {visit}",
    "p1:L3": "Prescriber: Dr. A. Example (fictional)",
    "p1:L5": "1. Amoxicillin 500 mg capsule: Take 1 capsule by mouth three times daily for 7 days.",
    "p1:L6": "2. Omeprazole 20 mg capsule: Take 1 capsule by mouth once daily before breakfast.",
    "p1:L7": "3. Ibuprofen 400 mg tablet: Take 1 tablet by mouth every 8 hours as needed for pain.",
    "p1:L9": "Take a short walk every morning.",
    "p1:L10": "Change the wound dressing every evening.",
    "p1:L11": "Contact the clinic if your pain score is 7 or higher for 2 consecutive days.",
    "p1:L12": "Seek emergency care if you have a fever above 39 C or trouble breathing.",
    "p1:L13": "Follow-up appointment on {follow_up} at Riverside Family Clinic.",
}
RULE = {"kind": "pain_score_at_or_above", "threshold": 7, "consecutive_days": 2}
# (line, record type, fields): what Maya approved on her screen three days ago. Labels are what Alexa says aloud;
# medicines get the document reader's own "Medicine routine N", never a drug name.
PLAN = [
    ("p1:L5", "PLAN_TASK", {"item_kind": "medication_task", "label": "Medicine routine 1", "medication": {"name": "Amoxicillin"},
                            "frequency": "three_times_daily", "times": ["08:00", "14:00", "20:00"]}),
    ("p1:L6", "PLAN_TASK", {"item_kind": "medication_task", "label": "Medicine routine 2", "medication": {"name": "Omeprazole"},
                            "frequency": "once_daily", "times": ["07:30"]}),
    ("p1:L7", "PLAN_TASK", {"item_kind": "medication_task", "label": "Medicine routine 3", "medication": {"name": "Ibuprofen"},
                            "frequency": "as_needed", "times": []}),
    ("p1:L9", "PLAN_TASK", {"item_kind": "care_task", "label": "Morning walk", "frequency": "once_daily", "times": ["08:00"]}),
    # Maya moved the dressing to 9 PM, when Sam is home.
    ("p1:L10", "PLAN_TASK", {"item_kind": "care_task", "label": "Evening dressing change", "frequency": "once_daily", "times": ["21:00"]}),
    ("p1:L11", "PLAN_RULE", {"item_kind": "rule_candidate", "label": "Pain follow-up rule", "rule_spec": RULE}),
    ("p1:L12", "PLAN_NOTE", {"item_kind": "warning_sign", "label": "When to get help"}),
    ("p1:L13", "PLAN_NOTE", {"item_kind": "appointment", "label": "Follow-up visit"}),
]
# Two days ago Maya checked her understanding: everything right except Omeprazole's time.
TEACH_BACK = [("p1:L5", "frequency", {"every_hours": 8}, None), ("p1:L6", "time", {"times": ["08:00"]}, "needs_clarification"),
              ("p1:L7", "as_needed", {"as_needed": True}, None), ("p1:L11", "threshold", {"number": 7}, None),
              ("p1:L11", "days", {"number": 2}, None), ("p1:L12", "number", {"number": 39}, None)]
HISTORY_PAIN = (3, 4, 7)  # three days ago, two days ago, yesterday
TODAY_PAIN = 5  # this morning; a high score on camera makes yesterday's 7 the first of two days


def seed_history(service: CareLoopService, patient: str, caregiver_id: str) -> dict[str, Any]:
    """Day four at home: an approved, cited plan and three days of history, so CareLoop has something to raise.

    The records are made through the service with its clock moved back, so every one is a real record
    with a believable time: approvals and Sam's invitation three days ago, his dressing change two days
    ago, a missed one yesterday that he has seen, and a teach-back two days ago with one answer to look at
    again. This morning Maya took the dressing back and checked in once (a 5), so the demo can start with
    "anything I should know?" and give the dressing to Sam again on camera.
    """
    from .teach_back import expected_for
    real_clock, now = service.clock, service._now()
    zone = service._zone(patient)
    today = datetime.fromtimestamp(now, zone).date()

    def at(days_ago: int, hour: int, minute: int = 0) -> int:
        day = today - timedelta(days=days_ago)
        return int(datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone).timestamp())

    def travel(when: int) -> None:
        service.clock = lambda: min(when, now)

    maya = Identity(patient, "patient", patient, "demo-seed")
    sam = Identity(caregiver_id, "caregiver", patient, "demo-seed")
    try:
        travel(at(3, 10))
        service.accept_data_use(maya)
        service.update_profile(maya, name=service.default_patient_name)
        service.storage.put(patient, "profile", "PATIENT", service.profile(patient) | {"demo_seed": SEED_TAG, "demo_story": "history"})
        invitation = service.invite(maya, CAREGIVER_SCOPES, name=CAREGIVER_NAME)
        service.accept_invitation(sam, invitation["id"])

        follow_up = (today + timedelta(days=6)).isoformat()  # outside the three days in which a visit is raised
        lines = {k: v.format(visit=(today - timedelta(days=3)).isoformat(), follow_up=follow_up) for k, v in LINES.items()}
        document = service.create_document(maya, "Prescription", [
            {"page": 1, "excerpt": text, "line_id": line, "method": "text", "confidence_pct": 100} for line, text in lines.items()],
            reviewed=True)
        items: dict[str, dict[str, Any]] = {}
        for order, (line, record_type, fields) in enumerate(PLAN, start=1):
            source = [{"id": line, "page": 1, "text": lines[line], "method": "text", "confidence_pct": 100}]
            payload = {"text": lines[line], "source": source, "page": 1, "order": order, "status": "active",
                       "approval_required": False, "approved_by": patient, "approved_at": at(3, 10, 5), "approved_on": "screen"} | fields
            if fields["item_kind"] == "appointment":
                payload["due_date"] = follow_up
            items[line] = service.write(maya, record_type, payload, source_id=document["id"], reviewed=True)

        travel(at(3, 10, 10))
        service.assign_task(maya, items["p1:L10"]["id"], invitation["id"])
        travel(at(3, 12))
        service.assigned_tasks(sam)  # Sam asked what his task was, which clears the new-task notice

        for days_ago, score in zip((3, 2, 1), HISTORY_PAIN):  # noon UTC, as the rule counts UTC days
            day = datetime.fromtimestamp(now, UTC).date() - timedelta(days=days_ago)
            when = int(datetime(day.year, day.month, day.day, 12, tzinfo=UTC).timestamp())
            travel(when)
            service.record_observation(maya, pain_score=score, observed_at=when, idempotency_key=f"demo-history-{day}")

        travel(at(2, 11))
        session = service._id()
        for line, check, heard, result in TEACH_BACK:
            item = items[line]
            service.record_teach_back(maya, item, check, result=result or "understood", attempts=2 if result else 1,
                                      expected=expected_for(item, check), heard=heard, session_id=session)
        travel(at(2, 16))
        service.add_clinician_question(maya, QUESTION)
        travel(at(2, 21, 20))
        service.record_task_completion(sam, items["p1:L10"]["id"])

        travel(at(1, 22, 5))  # an hour after yesterday's 9 PM dressing change, with nothing recorded
        missed = service.evaluate_missed_tasks(patient)
        travel(at(1, 22, 30))
        for alert in missed:
            service.acknowledge_alert(sam, alert["id"])  # Sam saw it, so his ring is dark this morning

        # This morning Maya took the dressing back after the miss, so nothing can count as missed today whatever
        # the time of day; giving it to Sam again is a moment in the demo. Then her morning check-in.
        travel(min(at(0, 7), now - 900))
        service.assign_task(maya, items["p1:L10"]["id"], None)
        travel(min(at(0, 9), now - 600))
        service.record_observation(maya, pain_score=TODAY_PAIN, idempotency_key=f"demo-history-{today}")
    finally:
        service.clock = real_clock
    return {"patient_name": service.patient_name(patient), "care_circle": [CAREGIVER_NAME], "story": "history",
            "pain_history": list(HISTORY_PAIN) + [TODAY_PAIN], "questions": 1, "plan_loaded": True,
            "missed_tasks": len(missed), "teach_back": "5 of 6 understood", "follow_up": follow_up}


def demo_story() -> str:
    """Which starting day to seed: CARELOOP_DEMO_STORY=history for "day four at home", else the first visit."""
    import os
    story = os.environ.get("CARELOOP_DEMO_STORY", "first-visit").strip().lower() or "first-visit"
    return story if story in STORIES else "first-visit"


def reset_demo(service: CareLoopService, patient: str, caregiver_id: str, story: str | None = None) -> dict[str, Any]:
    """Delete every record of the demo patient, then seed the chosen starting state again."""
    service.storage.wipe_patient(patient)
    if (story or demo_story()) == "history":
        return seed_history(service, patient, caregiver_id)
    return seed_demo(service, patient, caregiver_id)
