"""Demo seed and reset: the recorded story's starting day, and a reset that touches only the demo patient."""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from care_loop.auth import Identity, TokenAuth
from care_loop.config import Settings
from care_loop.core import CareLoopService
from care_loop.demo import PAIN_HISTORY, is_seeded, reset_demo, seed_demo
from care_loop.server import build_deps, create_app
from care_loop.storage import CareLoopStorage

PATIENT = Identity("demo-patient", "patient", "demo-patient")
SAM = Identity("demo-caregiver", "caregiver", "demo-patient")
PLAN = "\n".join(["TASK: Change the dressing | schedule: evening",
                  "RULE: PAIN_SCORE_AT_OR_ABOVE threshold=7 consecutive_days=2"])
NOW = int(datetime(2026, 10, 16, 15, 0, tzinfo=UTC).timestamp())


def service() -> CareLoopService:
    storage = CareLoopStorage(":memory:", clock=lambda: NOW)
    svc = CareLoopService(storage, clock=lambda: NOW, timezone="UTC")
    svc.default_patient_name = "Maya"  # as build_deps sets it from CARELOOP_DEMO_PATIENT_NAME
    return svc


def test_seed_is_the_starting_day_of_the_story() -> None:
    svc = service()
    seed_demo(svc, "demo-patient", "demo-caregiver")
    assert is_seeded(svc, "demo-patient") and svc.has_consented("demo-patient")
    assert svc.patient_name("demo-patient") == "Maya"
    assert svc.list_care_tasks(SAM) == []  # Sam is already in the circle; no plan yet
    assert [g["display_name"] for g in svc.list_grants(PATIENT) if g.get("accepted_at")] == ["Sam"]
    days = sorted((o["observed_at"], o["pain_score"]) for o in svc.list_observations(PATIENT))
    assert [score for _at, score in days] == list(PAIN_HISTORY)
    assert datetime.fromtimestamp(days[-1][0], UTC).date().isoformat() == "2026-10-15"  # yesterday
    assert svc.storage.list("demo-patient", "ALERT") == []
    assert [q["text"] for q in svc.clinician_questions(PATIENT)] == ["When can I go back to work?"]


def test_approved_rule_fires_on_the_next_high_score() -> None:
    svc = service()
    seed_demo(svc, "demo-patient", "demo-caregiver")
    for draft in svc.intake_text_document(PATIENT, "Prescription", PLAN)["drafts"]:
        svc.approve_plan_item(PATIENT, draft["id"])
    svc.record_observation(PATIENT, pain_score=8, idempotency_key="today")
    alerts = svc.storage.list("demo-patient", "ALERT")
    assert len(alerts) == 1 and alerts[0]["status"] == "active"


def test_reset_wipes_only_the_demo_patient() -> None:
    svc = service()
    other = Identity("someone-else", "patient", "someone-else")
    svc.accept_data_use(other)
    seed_demo(svc, "demo-patient", "demo-caregiver")
    svc.record_observation(PATIENT, pain_score=9, idempotency_key="today")
    reset_demo(svc, "demo-patient", "demo-caregiver")
    assert sorted(o["pain_score"] for o in svc.list_observations(PATIENT)) == sorted(PAIN_HISTORY)
    assert len(svc.list_grants(PATIENT)) == 1
    assert svc.has_consented("someone-else")


def test_reset_endpoint_is_off_unless_enabled_and_patient_only(tmp_path) -> None:
    auth = TokenAuth({"p": PATIENT, "c": SAM})
    off = build_deps(Settings(db_path=str(tmp_path / "off.db"), intake_llm="none", intake_ocr="none"), auth=auth)
    with TestClient(create_app(off)) as client:
        assert client.post("/api/care/demo/reset", headers={"authorization": "Bearer p"}).status_code == 404
    on = build_deps(Settings(db_path=str(tmp_path / "on.db"), intake_llm="none", intake_ocr="none",
                             demo_reset=True), auth=auth)
    with TestClient(create_app(on)) as client:
        assert client.post("/api/care/demo/reset", headers={"authorization": "Bearer c"}).status_code == 403
        response = client.post("/api/care/demo/reset", headers={"authorization": "Bearer p"})
    assert response.status_code == 200 and response.json()["seeded"]["care_circle"] == ["Sam"]
    assert is_seeded(on.service, "demo-patient")
