"""Suggestions: things worth raising, computed from the patient's own records. Deterministic, cited, never about symptoms."""
from __future__ import annotations

import json

import pytest

from care_loop.core import AccessDenied
from test_care_loop_family import PATIENT, SAM, Ctx, at, setup

QUESTION = "can I stop my medicine early"


def visit(service, due: str, status: str = "active"):
    return service.write(PATIENT, "PLAN_NOTE", {"item_kind": "appointment", "label": "Follow-up visit", "status": status,
                                                "text": f"Follow-up appointment on {due}.", "due_date": due}, reviewed=True)


def kinds(service):
    return [s["kind"] for s in service.suggestions(PATIENT)]


def checkin(service, hour: int, key: str, score: int = 4, day_offset: int = 0):
    service.record_observation(PATIENT, pain_score=score, observed_at=at(hour) + day_offset * 86_400, idempotency_key=key)


# ---- visit soon -------------------------------------------------------------------------------------------
@pytest.mark.parametrize("due, wording", [("2026-10-16", "today"), ("2026-10-17", "tomorrow"), ("2026-10-19", "in 3 days")])
def test_a_visit_within_three_days_is_raised_with_the_handoff_offer(due, wording) -> None:
    clock, service, *_ = setup()
    visit(service, due)
    (suggestion,) = [s for s in service.suggestions(PATIENT) if s["kind"] == "visit_soon"]
    assert suggestion["say"] == f"Your visit is {wording}."
    assert suggestion["offer"] == {"say": "Want me to prepare the handoff?", "tool": "create_visit_handoff",
                                   "arguments": {"from_date": "last_7_days"}}
    assert suggestion["source"]["type"] == "PLAN_NOTE"


@pytest.mark.parametrize("due", ["2026-10-20", "2026-10-15", "2025-01-01"])
def test_a_distant_or_past_visit_is_not_raised(due) -> None:
    clock, service, *_ = setup()
    visit(service, due)
    assert "visit_soon" not in kinds(service)


def test_an_unapproved_or_undated_visit_is_not_raised() -> None:
    clock, service, *_ = setup()
    visit(service, "2026-10-17", status="draft")
    service.write(PATIENT, "PLAN_NOTE", {"item_kind": "appointment", "label": "Visit", "status": "active", "text": "Follow up on 10/11"}, reviewed=True)
    assert "visit_soon" not in kinds(service)


def test_saved_questions_are_counted_never_quoted() -> None:
    clock, service, *_ = setup()
    visit(service, "2026-10-17")
    assert service.suggestions(PATIENT)[0]["say"] == "Your visit is tomorrow."
    service.add_clinician_question(PATIENT, QUESTION)
    service.add_clinician_question(PATIENT, "when can I swim")
    say = service.suggestions(PATIENT)[0]["say"]
    assert say == "Your visit is tomorrow. You have 2 questions saved for your clinician."
    assert "medicine" not in json.dumps(service.suggestions(PATIENT)).lower() and "swim" not in say


# ---- missed task ------------------------------------------------------------------------------------------
def test_a_missed_assigned_task_is_raised_once_it_is_missed_and_not_before() -> None:
    clock, service, deps, tools, invitation, tasks = setup()
    deps.local_identity = PATIENT
    tools["assign_task"](tasks["morning"]["id"], Ctx(), invitation["id"])  # due 08:00
    clock[0] = at(8, 30)
    assert "missed_task" not in kinds(service)  # inside the one-hour grace period
    clock[0] = at(9, 5)
    (suggestion,) = [s for s in service.suggestions(PATIENT) if s["kind"] == "missed_task"]
    assert suggestion["say"] == "Sam missed Take a short walk." and suggestion["offer"] is None


def test_a_missed_task_that_was_done_late_is_not_raised() -> None:
    clock, service, deps, tools, invitation, tasks = setup()
    deps.local_identity = PATIENT
    tools["assign_task"](tasks["morning"]["id"], Ctx(), invitation["id"])
    clock[0] = at(9, 5)
    assert "missed_task" in kinds(service)
    deps.local_identity = SAM
    tools["record_task_completion"](tasks["morning"]["id"], Ctx())  # Sam did it after all
    assert "missed_task" not in kinds(service)


def test_an_old_miss_is_no_longer_news() -> None:
    clock, service, deps, tools, invitation, tasks = setup()
    deps.local_identity = PATIENT
    tools["assign_task"](tasks["morning"]["id"], Ctx(), invitation["id"])
    clock[0] = at(9, 5)
    assert "missed_task" in kinds(service)
    tools["assign_task"](tasks["morning"]["id"], Ctx())  # taken back, so nothing new can be missed
    clock[0] = at(9, 5) + 3 * 86_400
    assert "missed_task" not in kinds(service)


def test_several_misses_are_counted() -> None:
    clock, service, deps, tools, invitation, tasks = setup()
    deps.local_identity = PATIENT
    tools["assign_task"](tasks["morning"]["id"], Ctx(), invitation["id"])
    tools["assign_task"](tasks["evening"]["id"], Ctx(), invitation["id"])
    clock[0] = at(21)
    (suggestion,) = [s for s in service.suggestions(PATIENT) if s["kind"] == "missed_task"]
    assert suggestion["say"] == "2 tasks were missed in the last 2 days."


# ---- no check-in today ------------------------------------------------------------------------------------
def test_no_checkin_today_is_raised_after_the_hour_for_someone_who_has_checked_in_before() -> None:
    clock, service, *_ = setup()
    checkin(service, 12, "yesterday", day_offset=-1)
    clock[0] = at(17, 59)
    assert "no_checkin" not in kinds(service)  # too early in the day
    clock[0] = at(18)
    (suggestion,) = [s for s in service.suggestions(PATIENT) if s["kind"] == "no_checkin"]
    assert suggestion["say"] == "You haven't checked in today."
    assert suggestion["offer"] == {"say": "Want to do your check-in now?", "tool": "start_daily_checkin", "arguments": {}}


def test_a_new_user_and_someone_who_checked_in_today_are_not_nagged() -> None:
    clock, service, *_ = setup()
    clock[0] = at(20)
    assert "no_checkin" not in kinds(service)  # never checked in at all
    checkin(service, 12, "yesterday", day_offset=-1)
    checkin(service, 19, "today")
    assert "no_checkin" not in kinds(service)


def test_a_correction_is_not_a_check_in_and_the_hour_is_configurable() -> None:
    clock, service, *_ = setup()
    service.suggest_checkin_hour = 8
    checkin(service, 12, "yesterday", day_offset=-1)
    clock[0] = at(9)
    assert "no_checkin" in kinds(service)


def test_the_local_day_follows_the_patients_time_zone() -> None:
    clock, service, *_ = setup()
    service.update_profile(PATIENT, timezone="Asia/Dhaka")  # UTC+6
    checkin(service, 12, "yesterday", day_offset=-1)
    clock[0] = at(14)  # 20:00 in Dhaka: after the hour there
    assert "no_checkin" in kinds(service)
    clock[0] = at(7)   # 13:00 in Dhaka: before it
    assert "no_checkin" not in kinds(service)


# ---- review waiting ---------------------------------------------------------------------------------------
def test_unreviewed_plan_items_are_raised_with_the_review_offer() -> None:
    clock, service, *_ = setup()
    assert "review_waiting" not in kinds(service)
    service.intake_text_document(PATIENT, "New plan", "TASK: Drink water | schedule: morning")
    (suggestion,) = [s for s in service.suggestions(PATIENT) if s["kind"] == "review_waiting"]
    assert suggestion["say"] == "1 plan item is waiting for your review."
    assert suggestion["offer"]["tool"] == "review_plan_by_voice"


# ---- ordering, limits, privacy ----------------------------------------------------------------------------
def test_order_cap_and_stable_ids() -> None:
    clock, service, deps, tools, invitation, tasks = setup()
    visit(service, "2026-10-17")
    deps.local_identity = PATIENT
    tools["assign_task"](tasks["morning"]["id"], Ctx(), invitation["id"])
    checkin(service, 12, "yesterday", day_offset=-1)
    service.intake_text_document(PATIENT, "New plan", "TASK: Drink water | schedule: morning")
    clock[0] = at(21)
    first = service.suggestions(PATIENT)
    assert [s["kind"] for s in first] == ["visit_soon", "missed_task", "no_checkin"]  # four apply, three are kept, in order
    assert [s["id"] for s in service.suggestions(PATIENT)] == [s["id"] for s in first]  # the same ids on the same day
    clock[0] += 86_400
    assert {s["id"] for s in service.suggestions(PATIENT)}.isdisjoint({s["id"] for s in first})  # a new day, new ids


def test_nothing_to_raise_gives_an_empty_list_and_nothing_is_stored() -> None:
    clock, service, *_ = setup()
    before = len(service.storage.list("demo-patient"))
    assert service.suggestions(PATIENT) == []
    assert len(service.storage.list("demo-patient")) == before


def test_suggestions_can_be_turned_off_and_on() -> None:
    clock, service, *_ = setup()
    visit(service, "2026-10-17")
    assert service.suggestions_enabled("demo-patient") and service.suggestions(PATIENT)
    service.update_profile(PATIENT, suggestions=False)
    assert not service.suggestions_enabled("demo-patient") and service.suggestions(PATIENT) == []
    service.update_profile(PATIENT, suggestions=True)
    assert service.suggestions(PATIENT)


def test_a_family_member_gets_no_suggestions() -> None:
    clock, service, *_ = setup()
    visit(service, "2026-10-17")
    with pytest.raises(AccessDenied):
        service.suggestions(SAM)


def test_no_suggestion_carries_a_score_or_question_text() -> None:
    clock, service, deps, tools, invitation, tasks = setup()
    visit(service, "2026-10-17")
    service.add_clinician_question(PATIENT, QUESTION)
    checkin(service, 12, "yesterday", score=9, day_offset=-1)
    clock[0] = at(21)
    text = json.dumps(service.suggestions(PATIENT)).lower()
    assert "medicine" not in text and "pain" not in text and "9" not in "".join(s["say"] for s in service.suggestions(PATIENT))


# ---- the MCP tool ---------------------------------------------------------------------------------------
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402


def test_the_tool_speaks_the_suggestion_and_carries_its_offer() -> None:
    clock, service, deps, tools, *_ = setup()
    visit(service, "2026-10-17")
    service.add_clinician_question(PATIENT, QUESTION)
    result = tools["get_suggestions"](Ctx())
    assert result["speakable"] == ("Your visit is tomorrow. You have 1 question saved for your clinician. "
                                   "Want me to prepare the handoff?")
    assert result["next_step"] == {"say": "Want me to prepare the handoff?", "tool": "create_visit_handoff",
                                   "arguments": {"from_date": "last_7_days"}}
    assert result["view"] == "ui://careloop/tasks" and [r["kind"] for r in result["refs"]] == ["suggestion"]
    assert QUESTION not in json.dumps(result)


def test_several_suggestions_are_counted_and_only_the_first_offer_is_asked() -> None:
    clock, service, deps, tools, invitation, tasks = setup()
    visit(service, "2026-10-17")
    checkin(service, 12, "yesterday", day_offset=-1)
    clock[0] = at(20)
    result = tools["get_suggestions"](Ctx())
    # the offer is for the visit, so the visit comes last, right before its question
    assert result["speakable"] == ("You have 2 things worth a look. You haven't checked in today. "
                                   "Your visit is tomorrow. Want me to prepare the handoff?")
    assert result["next_step"]["tool"] == "create_visit_handoff" and len(result["refs"]) == 2


def test_nothing_to_raise_says_so_and_offers_nothing() -> None:
    clock, service, deps, tools, *_ = setup()
    result = tools["get_suggestions"](Ctx())
    assert result["speakable"] == "Nothing needs your attention right now."
    assert not result.get("next_step") and result["refs"] == []


def test_a_suggestion_without_a_question_offers_no_next_step() -> None:
    clock, service, deps, tools, invitation, tasks = setup()
    tools["assign_task"](tasks["morning"]["id"], Ctx(), invitation["id"])
    clock[0] = at(9, 5)
    result = tools["get_suggestions"](Ctx())
    assert result["speakable"] == "Sam missed Take a short walk." and not result.get("next_step")


def test_a_family_member_cannot_ask_for_suggestions() -> None:
    clock, service, deps, tools, *_ = setup()
    visit(service, "2026-10-17")
    deps.local_identity = SAM
    with pytest.raises(ToolError, match="Suggestions are unavailable"):
        tools["get_suggestions"](Ctx())


def test_the_patient_can_turn_suggestions_off_and_back_on_by_voice() -> None:
    clock, service, deps, tools, *_ = setup()
    visit(service, "2026-10-17")
    assert tools["set_my_details"](Ctx(), suggestions=False)["speakable"] == "Done. suggestions are off."
    assert tools["get_suggestions"](Ctx())["speakable"].startswith("Suggestions are turned off.")
    assert tools["set_my_details"](Ctx(), suggestions=True)["speakable"] == "Done. suggestions are on."
    assert tools["get_suggestions"](Ctx())["speakable"].startswith("Your visit is tomorrow.")
    assert tools["get_suggestions"](Ctx())["speakable"].endswith("Want me to prepare the handoff?")
    assert tools["set_my_details"](Ctx())["speakable"] == "Nothing changed."


def test_a_later_suggestion_still_gets_its_question_when_the_first_has_none() -> None:
    clock, service, deps, tools, invitation, tasks = setup()
    tools["assign_task"](tasks["morning"]["id"], Ctx(), invitation["id"])
    clock[0] = at(9, 5)
    service.intake_text_document(PATIENT, "New plan", "TASK: Drink water | schedule: morning")  # review waiting: has a question
    result = tools["get_suggestions"](Ctx())
    assert result["speakable"] == ("You have 2 things worth a look. Sam missed Take a short walk. "
                                   "1 plan item is waiting for your review. Want to go through them now?")
    assert result["next_step"]["tool"] == "review_plan_by_voice"
