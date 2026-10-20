"""Every claim on the patient's private screen says where it came from: a document line, or the record it
was computed from. Family screens stay generic on purpose."""
from __future__ import annotations

import asyncio
import json

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from test_care_loop_teach_back import ALL_RIGHT, NOW, PATIENT, SAM, Script, world


def view(tools, name, record_ids=None):
    return tools["get_private_view"](name, Script(), record_ids)["data"]


@pytest.fixture()
def full_day():
    """A day with something in every section: a fired rule, a missed and a done task, a question, a visit, a teach-back."""
    clock, service, deps, tools, items = world()
    invitation = service.invite(PATIENT, ["read_tasks", "read_observations", "perform_tasks", "receive_alerts"], name="Sam")
    service.accept_invitation(SAM, invitation["id"])
    service.record_observation(PATIENT, pain_score=7, observed_at=NOW - 86_400, idempotency_key="yesterday")
    service.record_observation(PATIENT, pain_score=8, observed_at=NOW - 3600, idempotency_key="today")
    clock[0] = NOW - 12 * 3600  # 06:00, before the 08:00 walk
    service.assign_task(PATIENT, items["walk"]["id"], invitation["id"])
    clock[0] = NOW
    service.record_task_completion(PATIENT, items["omeprazole"]["id"])
    service.add_clinician_question(PATIENT, "can I shower with the dressing on")
    service.write(PATIENT, "PLAN_NOTE", {"item_kind": "appointment", "label": "Visit", "status": "active",
                                         "text": "Follow-up on 2026-10-17.", "due_date": "2026-10-17"}, reviewed=True)
    asyncio.run(tools["start_teach_back"](Script("I don't know", *ALL_RIGHT[1:])))
    service.create_visit_handoff(PATIENT, NOW - 7 * 86_400, NOW + 60)
    return clock, service, deps, tools, items


def cited(entry):
    citation = entry.get("citation") or entry.get("source_citation") or (entry.get("because") or {}).get("citation")
    return bool(citation and (citation.get("excerpts") or citation.get("page_excerpts")))


def test_every_plan_item_and_suggestion_on_the_task_screen_says_where_it_came_from(full_day) -> None:
    _clock, _service, _deps, tools, _items = full_day
    data = view(tools, "tasks")
    plan = [i for i in data["items"] if i.get("source_id")]
    assert plan and all(cited(i) for i in plan)
    kinds = {s["kind"] for s in data["suggestions"]}
    assert kinds == {"visit_soon", "missed_task", "teach_back_due"}
    for suggestion in data["suggestions"]:
        assert suggestion["because"]["label"]
    by_kind = {s["kind"]: s for s in data["suggestions"]}
    assert by_kind["missed_task"]["because"]["label"] == "Morning walk was due"
    assert [e["line_id"] for e in by_kind["missed_task"]["because"]["citation"]["excerpts"]] == ["p1:L10"]
    assert [e["line_id"] for e in by_kind["teach_back_due"]["because"]["citation"]["excerpts"]] == ["p1:L3"]


def test_the_trend_shows_the_alert_line_with_its_rule_and_who_recorded_each_value(full_day) -> None:
    _clock, _service, _deps, tools, _items = full_day
    data = view(tools, "check-in-trend")
    (rule,) = data["rules"]
    assert (rule["threshold"], rule["consecutive_days"]) == (7, 2) and data["thresholds"] == [7]
    assert [e["line_id"] for e in rule["citation"]["excerpts"]] == ["p1:L9"]
    assert {o["recorded_by"] for o in data["observations"]} == {"you"}


def test_every_handoff_entry_says_where_it_came_from(full_day) -> None:
    _clock, _service, _deps, tools, items = full_day
    handoff = view(tools, "visit-handoff")["handoff"]
    for section in ("plan_items", "task_events", "alerts", "understanding"):
        assert handoff[section], section
        for entry in handoff[section]:
            if section == "plan_items" and not entry.get("source_id"):
                continue  # the visit note was written by hand in this test, with no document
            assert cited(entry), (section, entry)
    (fired,) = [a for a in handoff["alerts"] if a.get("kind", "rule") == "rule"]
    assert [o["pain_score"] for o in fired["trigger_observations"]] == [7, 8]
    assert [e["line_id"] for e in fired["source_citation"]["page_excerpts"]] == ["p1:L9"]
    (missed,) = [a for a in handoff["alerts"] if a.get("kind") == "missed_task"]
    assert [e["line_id"] for e in missed["source_citation"]["page_excerpts"]] == ["p1:L10"]
    (done,) = handoff["task_events"]
    assert done["task_label"] == "Stomach medicine"


def test_every_teach_back_row_carries_its_lines_and_its_result(full_day) -> None:
    _clock, _service, _deps, tools, _items = full_day
    checks = view(tools, "teach-back")["checks"]
    assert len(checks) == 6 and all(cited(c) for c in checks)
    assert [c["result"] for c in checks].count("needs_clarification") == 1


def test_who_looked_carries_the_date_of_the_last_action(full_day) -> None:
    _clock, _service, deps, tools, _items = full_day
    deps.local_identity = SAM
    view(tools, "tasks")
    deps.local_identity = PATIENT
    (sam,) = view(tools, "care-circle")["access"]
    assert sam["name"] == "Sam" and sam["last_at"] == NOW


def test_a_family_member_sees_no_provenance_suggestions_or_teach_back(full_day) -> None:
    _clock, _service, deps, tools, _items = full_day
    deps.local_identity = SAM
    tasks = view(tools, "tasks")
    trend = view(tools, "check-in-trend")
    text = json.dumps([tasks, trend])
    assert "suggestions" not in tasks and "because" not in text and "rules" not in trend and "recorded_by" not in text
    for private in ("teach-back", "visit-handoff"):
        with pytest.raises(ToolError):
            view(tools, private)


def test_a_handoff_saved_before_provenance_still_opens(full_day) -> None:
    _clock, service, _deps, tools, _items = full_day
    old = service.write(PATIENT, "HANDOFF", {
        "label": "Patient-generated factual summary for clinician discussion", "from_date": NOW - 86_400, "to_date": NOW,
        "plan_items": [], "task_events": [{"task_id": "x", "completed_at": NOW}], "observations": [],
        "alerts": [{"kind": "rule", "status": "active", "acknowledgements": []}], "questions": [], "corrections": [],
        "uncertainties": [], "totals": {"plan_items": 0, "task_events": 1, "observations": 0, "alerts": 1}}, reviewed=True)
    handoff = view(tools, "visit-handoff", [old["id"]])["handoff"]
    assert handoff["id"] == old["id"] and "understanding" not in handoff
