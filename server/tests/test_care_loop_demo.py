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


def test_document_reading_keeps_its_ollama_address_when_the_planner_is_openai_compatible() -> None:
    gateway = "https://gw.example/v1/chat/completions"
    assert Settings.from_env({"LLM_BASE_URL": gateway, "CARELOOP_AGENT_LLM": "openai"}).llm_base_url == "http://127.0.0.1:11434"
    assert Settings.from_env({"LLM_BASE_URL": "http://box:11434"}).llm_base_url == "http://box:11434"
    assert Settings.from_env({"LLM_BASE_URL": gateway, "CARELOOP_AGENT_LLM": "openai",
                              "CARELOOP_INTAKE_BASE_URL": "http://box:11434"}).llm_base_url == "http://box:11434"


# ---- "day four at home": history for suggestions, teach-back and the handoff ---------------------------------
import asyncio  # noqa: E402

import pytest  # noqa: E402

from care_loop.demo import demo_story, seed_history  # noqa: E402


def history_at(hour: int, minute: int = 0, zone: str = "UTC"):
    when = int(datetime(2026, 10, 16, hour, minute, tzinfo=UTC).timestamp())
    clock = [when]
    storage = CareLoopStorage(":memory:", clock=lambda: clock[0])
    svc = CareLoopService(storage, clock=lambda: clock[0], timezone=zone)
    svc.default_patient_name = "Maya"
    summary = seed_history(svc, "demo-patient", "demo-caregiver")
    return clock, svc, summary


@pytest.mark.parametrize("hour, minute", [(6, 30), (12, 0), (21, 30), (23, 45)])
def test_history_raises_the_same_two_things_at_any_time_of_day(hour, minute) -> None:
    _clock, svc, summary = history_at(hour, minute)
    assert summary["story"] == "history" and summary["missed_tasks"] == 1
    found = svc.suggestions(PATIENT)
    assert [s["kind"] for s in found] == ["missed_task", "teach_back_due"]
    assert found[0]["say"] == "Sam missed Evening dressing change."
    assert found[1]["say"] == "Part of your plan needs another look." and found[1]["offer"]["tool"] == "start_teach_back"


def test_history_has_an_approved_cited_plan_and_three_days_of_records() -> None:
    _clock, svc, _summary = history_at(12)
    plan = svc.list_care_tasks(PATIENT)
    assert len(plan) == 8 and all(i["status"] == "active" and i["source"] for i in plan)
    assert [o["pain_score"] for o in svc.list_observations(PATIENT)] == [3, 4, 7, 5]
    assert svc.storage.list("demo-patient", "ALERT")[0]["acknowledgements"]  # Sam saw yesterday's miss: his ring is dark
    assert svc.notifications(SAM)[0]["status"] == "acknowledged"
    dressing = next(t for t in plan if t.get("label") == "Evening dressing change")
    assert dressing["times"] == ["21:00"] and not dressing.get("assignee_id")  # Maya took it back this morning
    assert [q["text"] for q in svc.clinician_questions(PATIENT)] == ["When can I go back to work?"]


def test_history_rule_fires_on_the_next_high_score_and_the_teach_back_asks_one_thing() -> None:
    from care_loop.tools.records import register
    from test_care_loop_teach_back import Deps, FakeMCP, Script
    _clock, svc, _summary = history_at(15)
    svc.record_observation(PATIENT, pain_score=8, idempotency_key="on-camera")
    fired = [a for a in svc.storage.list("demo-patient", "ALERT") if a.get("rule_id")]
    assert len(fired) == 1 and len(fired[0]["observation_ids"]) == 2
    mcp = FakeMCP()
    register(mcp, Deps(svc))
    person = Script("8 am", "7:30 in the morning")
    result = asyncio.run(mcp.tools["start_teach_back"](person))
    assert person.asked == ["Let's check 1 thing. When do you take Omeprazole?", "Not quite. Try again: When do you take Omeprazole?"]
    assert result["speakable"] == "That's right. Done. You got 1 of 1 right."


def test_the_story_is_chosen_by_environment_and_reset_follows_it(monkeypatch) -> None:
    monkeypatch.delenv("CARELOOP_DEMO_STORY", raising=False)
    assert demo_story() == "first-visit"
    monkeypatch.setenv("CARELOOP_DEMO_STORY", "history")
    svc = service()
    assert reset_demo(svc, "demo-patient", "demo-caregiver")["story"] == "history"
    monkeypatch.setenv("CARELOOP_DEMO_STORY", "something-else")
    assert demo_story() == "first-visit"
