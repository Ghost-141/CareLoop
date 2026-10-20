"""Teach-back: the patient says back key values of the approved plan, and code checks each answer.

Questions come from the cited item's own fields; a miss is answered by reading the plan back, never by
explaining. Only the structured value heard is stored, never the person's words.
"""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from care_loop.auth import Identity
from care_loop.core import AccessDenied, CareLoopService
from care_loop.storage import CareLoopStorage
from care_loop.teach_back import checks_for, expected_for, interpret, is_dont_know, is_stop, matches, question_for
from care_loop.tools.records import register

PATIENT = Identity("demo-patient", "patient", "demo-patient")
SAM = Identity("demo-caregiver", "caregiver", "demo-patient")
NOW = int(datetime(2026, 10, 16, 18, 0, tzinfo=UTC).timestamp())
LINES = {
    "p1:L3": "Amoxicillin 500 mg by mouth every 8 hours for 7 days.",
    "p1:L4": "Omeprazole 20 mg every morning before breakfast.",
    "p1:L5": "Ibuprofen 400 mg every 6 hours as needed for pain.",
    "p1:L8": "Seek emergency care if you have a fever above 39 C.",
    "p1:L9": "Call the clinic if your pain is 7 or higher for 2 days in a row.",
    "p1:L10": "Take a short walk every morning.",
}
ALL_RIGHT = ["every 8 hours", "8 in the morning", "only when I need it", "39", "7", "2"]


class FakeMCP:
    def __init__(self) -> None:
        self.tools = {}

    def tool(self, *, name, title=None, annotations=None, meta=None):
        def register_tool(fn):
            self.tools[name] = fn
            return fn
        return register_tool


class Deps:
    def __init__(self, service):
        self.service, self.local_identity = service, PATIENT

    def identity(self, _ctx):
        return self.local_identity


class Script:
    """A scripted person answering MCP elicitations, in order. A string that is an action name declines."""

    def __init__(self, *answers) -> None:
        self.answers, self.asked = list(answers), []
        self.headers = None

    async def elicit(self, message, schema):
        self.asked.append(message)
        answer = self.answers.pop(0)
        if answer in {"decline", "cancel"}:
            return type("Reply", (), {"action": answer})()
        return type("Reply", (), {"action": "accept", "data": schema(answer=answer)})()


def world(*, medicines=True):
    clock = [NOW]
    service = CareLoopService(CareLoopStorage(":memory:", clock=lambda: clock[0]), clock=lambda: clock[0], timezone="UTC")
    deps = Deps(service)
    mcp = FakeMCP()
    register(mcp, deps)
    doc = service.create_document(PATIENT, "Discharge plan", [{"page": 1, "excerpt": text, "line_id": line}
                                                             for line, text in LINES.items()], reviewed=True)

    def item(record_type, line, **fields):
        source = [{"id": line, "page": 1, "text": LINES[line], "method": "text", "confidence_pct": 100}]
        return service.write(PATIENT, record_type, {"status": "active", "text": LINES[line], "source": source, "page": 1} | fields,
                             source_id=doc["id"], reviewed=True)

    items = {}
    if medicines:
        items["amoxicillin"] = item("PLAN_TASK", "p1:L3", item_kind="medication_task", label="Antibiotic",
                                    medication={"name": "Amoxicillin"}, frequency="three_times_daily",
                                    times=["08:00", "14:00", "20:00"])
        items["omeprazole"] = item("PLAN_TASK", "p1:L4", item_kind="medication_task", label="Stomach medicine",
                                   medication={"name": "Omeprazole"}, frequency="once_daily", times=["08:00"])
        items["ibuprofen"] = item("PLAN_TASK", "p1:L5", item_kind="medication_task", label="Pain relief",
                                  medication={"name": "Ibuprofen"}, frequency="as_needed", times=[])
        items["fever"] = item("PLAN_NOTE", "p1:L8", item_kind="warning_sign", label="Fever warning")
        items["rule"] = item("PLAN_RULE", "p1:L9", item_kind="rule_candidate", label="Follow-up rule",
                             rule_spec={"kind": "pain_score_at_or_above", "threshold": 7, "consecutive_days": 2})
    items["walk"] = item("PLAN_TASK", "p1:L10", item_kind="care_task", label="Morning walk", frequency="once_daily", times=["08:00"])
    return clock, service, deps, mcp.tools, items


def run(coroutine):
    return asyncio.run(coroutine)


def results(service):
    return {(r["item_id"], r["check"]): r for r in service.storage.list("demo-patient", "TEACH_BACK")}


# ---- which values are checked, and how ------------------------------------------------------------------
def test_only_medicines_rules_and_a_single_number_warning_are_checked_in_document_order() -> None:
    _clock, service, _deps, _tools, items = world()
    checks = [(c["item"]["id"], c["check"]) for c in service.teach_back_checks(PATIENT)]
    assert checks == [(items["amoxicillin"]["id"], "frequency"), (items["omeprazole"]["id"], "time"),
                      (items["ibuprofen"]["id"], "as_needed"), (items["fever"]["id"], "number"),
                      (items["rule"]["id"], "threshold"), (items["rule"]["id"], "days")]


def test_a_name_without_letters_falls_back_to_the_spoken_label() -> None:
    item = {"id": "x", "type": "PLAN_TASK", "status": "active", "item_kind": "medication_task", "label": "Medicine routine 1",
            "medication": {"name": "1."}, "frequency": "three_times_daily", "times": ["08:00", "14:00", "20:00"]}
    assert question_for(item, "frequency") == "How often do you take Medicine routine 1?"


@pytest.mark.parametrize("fields", [
    {"type": "PLAN_TASK", "item_kind": "care_task", "frequency": "once_daily", "times": ["08:00"]},  # a walk is not quizzed
    {"type": "PLAN_TASK", "item_kind": "medication_task", "frequency": "weekly", "times": ["09:00"]},
    {"type": "PLAN_TASK", "item_kind": "medication_task", "frequency": "unspecified", "times": []},
    {"type": "PLAN_NOTE", "item_kind": "warning_sign", "text": "Call if fever is between 38 and 39 C."},  # two numbers
    {"type": "PLAN_NOTE", "item_kind": "warning_sign", "text": "Call if the wound bleeds."},  # no number
    {"type": "PLAN_NOTE", "item_kind": "warning_sign", "text": "Call if you vomit more than 3 times."},  # not a temperature
    {"type": "PLAN_NOTE", "item_kind": "appointment", "text": "Follow-up on 2026-10-24."},
])
def test_values_that_cannot_be_checked_are_never_asked(fields) -> None:
    assert checks_for({"id": "x", "status": "active"} | fields) == []


def test_a_draft_is_never_asked() -> None:
    assert checks_for({"id": "x", "type": "PLAN_TASK", "status": "draft", "item_kind": "medication_task",
                       "frequency": "as_needed"}) == []


def test_questions_use_the_medicine_name_as_written() -> None:
    _clock, _service, _deps, _tools, items = world()
    assert question_for(items["amoxicillin"], "frequency") == "How often do you take Amoxicillin?"
    assert question_for(items["omeprazole"], "time") == "When do you take Omeprazole?"
    assert question_for(items["ibuprofen"], "as_needed") == "Do you take Ibuprofen at set times, or only when you need it?"
    assert expected_for(items["fever"], "number") == {"number": 39.0}
    assert expected_for(items["rule"], "threshold") == {"number": 7.0} and expected_for(items["rule"], "days") == {"number": 2.0}


@pytest.mark.parametrize("answer, right", [
    ("every 8 hours", True), ("three times a day", True), ("3 times daily", True), ("every eight hours", True),
    ("8 am, 2 pm and 8 pm", True), ("twice a day", False), ("every 6 hours", False), ("when I need it", False),
    ("with food", False)])
def test_frequency_answers(answer, right) -> None:
    expected = {"every_hours": 8.0}
    assert matches("frequency", expected, interpret("frequency", answer, expected)) is right


def test_an_every_n_hours_medicine_accepts_the_same_interval_in_doses_per_day() -> None:
    item = {"id": "x", "type": "PLAN_TASK", "status": "active", "item_kind": "medication_task",
            "frequency": "every_n_hours", "interval_hours": 12, "times": ["08:00", "20:00"]}
    expected = expected_for(item, "frequency")
    assert matches("frequency", expected, interpret("frequency", "every 12 hours", expected))
    assert matches("frequency", expected, interpret("frequency", "twice a day", expected))


@pytest.mark.parametrize("answer, right", [
    ("8 am", True), ("8", True), ("eight in the morning", True), ("at 8:00", True), ("in the morning", True),
    ("with breakfast", True), ("8 pm", False), ("9 am", False), ("in the evening", False), ("at night", False),
    ("after my walk", False)])
def test_time_answers_for_an_8_am_medicine(answer, right) -> None:
    expected = {"time": "08:00"}
    assert matches("time", expected, interpret("time", answer, expected)) is right


def test_a_bare_hour_takes_am_or_pm_from_the_plan_time_and_a_period_word_wins() -> None:
    expected = {"time": "21:00"}
    assert matches("time", expected, interpret("time", "9", expected))
    assert not matches("time", expected, interpret("time", "9 in the morning", expected))
    assert matches("time", expected, interpret("time", "at night", expected))  # a period covers a single plan time


@pytest.mark.parametrize("answer, as_needed", [
    ("only when I need it", True), ("as needed", True), ("if I need it", True), ("when the pain is bad", True),
    ("at set times", False), ("every day", False), ("twice a day", False), ("I'm not really sure what you mean", None)])
def test_as_needed_answers(answer, as_needed) -> None:
    heard = interpret("as_needed", answer, {"as_needed": True})
    assert (heard or {}).get("as_needed") is as_needed


@pytest.mark.parametrize("answer, number", [("39", 39.0), ("39 degrees", 39.0), ("38.5", 38.5), ("seven", 7.0), ("hmm", None)])
def test_number_answers(answer, number) -> None:
    assert (interpret("number", answer, {"number": 39.0}) or {}).get("number") == number


def test_stop_and_dont_know_are_recognised() -> None:
    assert is_stop("stop") and is_stop("that's enough") and not is_stop("every 8 hours, don't stop")
    assert is_dont_know("I don't know") and is_dont_know("not sure") and is_dont_know("I forgot") and not is_dont_know("39")


# ---- the conversation --------------------------------------------------------------------------------
def test_all_right_answers_end_with_the_count() -> None:
    _clock, service, _deps, tools, items = world()
    person = Script(*ALL_RIGHT)
    result = run(tools["start_teach_back"](person))
    assert person.asked[:3] == ["Let's check 6 things. How often do you take Amoxicillin?",
                                "That's right. When do you take Omeprazole?",
                                "That's right. Do you take Ibuprofen at set times, or only when you need it?"]
    assert person.asked[4:] == ["That's right. Your plan has an alert rule for pain. At what pain score does it start?",
                                "That's right. For how many days in a row?"]
    assert result["speakable"] == "That's right. Done. You got 6 of 6 right."
    assert result["view"] == "ui://careloop/teach-back"
    assert {r["result"] for r in results(service).values()} == {"understood"}


def test_a_wrong_answer_gets_a_second_try() -> None:
    _clock, service, _deps, tools, items = world()
    person = Script("twice a day", "three times a day", "stop")
    run(tools["start_teach_back"](person))
    assert person.asked[1] == "Not quite. Try again: How often do you take Amoxicillin?"
    assert person.asked[2] == "That's right. When do you take Omeprazole?"
    row = results(service)[(items["amoxicillin"]["id"], "frequency")]
    assert row["result"] == "understood" and row["attempts"] == 2


def test_two_misses_read_the_plan_back_in_its_own_words_and_move_on() -> None:
    _clock, service, _deps, tools, items = world()
    person = Script("twice a day", "every 12 hours", "stop")
    run(tools["start_teach_back"](person))
    assert person.asked[2] == ("Your plan says: Amoxicillin 500 mg by mouth every 8 hours for 7 days, at 8 AM, 2 PM and 8 PM. "
                               "Next: When do you take Omeprazole?")
    row = results(service)[(items["amoxicillin"]["id"], "frequency")]
    assert row["result"] == "needs_clarification" and row["attempts"] == 2
    assert row["heard"] == {"every_hours": 12.0} and row["expected"] == {"every_hours": 8.0}


def test_dont_know_moves_on_after_one_try_without_a_second_question() -> None:
    _clock, service, _deps, tools, items = world()
    person = Script("I don't know", "stop")
    run(tools["start_teach_back"](person))
    assert person.asked[1].startswith("That's okay. Your plan says: Amoxicillin 500 mg")
    row = results(service)[(items["amoxicillin"]["id"], "frequency")]
    assert row["result"] == "needs_clarification" and row["attempts"] == 1 and row["heard"] is None


def test_stop_saves_the_place_and_check_my_understanding_resumes_it() -> None:
    _clock, service, _deps, tools, items = world()
    first = Script("every 8 hours", "stop")
    paused = run(tools["start_teach_back"](first))
    assert paused["speakable"] == 'Okay, I\'ve saved your place. 5 questions left. Say "check my understanding" anytime.'
    second = Script(*ALL_RIGHT[1:])
    finished = run(tools["start_teach_back"](second))
    assert second.asked[0] == "Let's pick up where we left off. When do you take Omeprazole?"
    assert finished["speakable"] == "That's right. Done. You got 6 of 6 right."


def test_declining_the_question_also_saves_the_place() -> None:
    _clock, service, _deps, tools, items = world()
    assert run(tools["start_teach_back"](Script("decline")))["speakable"].startswith("Okay, I've saved your place. 6 questions")
    assert service.active_workflow(PATIENT, "teach_back") is not None


def test_three_misses_in_a_row_leave_the_rest_for_the_clinician() -> None:
    _clock, service, _deps, tools, items = world()
    person = Script("I don't know", "not sure", "no idea")
    result = run(tools["start_teach_back"](person))
    assert result["speakable"] == ("Let's leave the rest for your clinician. You got 0 of 3 right, "
                                   "and I've noted it for your visit handoff.")
    assert len(person.asked) == 3
    by_result = [r["result"] for r in sorted(results(service).values(), key=lambda r: r["created_at"])]
    assert by_result.count("needs_clarification") == 3 and by_result.count("skipped") == 3
    assert service.active_workflow(PATIENT, "teach_back") is None


def test_a_miss_then_a_right_answer_resets_the_streak() -> None:
    _clock, service, _deps, tools, items = world()
    result = run(tools["start_teach_back"](Script("I don't know", "not sure", *ALL_RIGHT[2:])))
    assert result["speakable"] == ("That's right. Done. You got 4 of 6 right. The ones to look at again are on your "
                                   "screen, with the lines they came from.")


def test_the_end_of_a_session_with_misses_points_to_the_screen_without_plan_text() -> None:
    _clock, service, _deps, tools, items = world()
    result = run(tools["start_teach_back"](Script(*ALL_RIGHT[:5], "I don't know")))
    assert result["speakable"] == ("Done. You got 5 of 6 right. The one to look at again is on your screen, "
                                   "with the line it came from.")
    assert "Amoxicillin" not in result["speakable"] and "pain" not in result["speakable"]


def test_nothing_to_check_says_so() -> None:
    _clock, _service, _deps, tools, _items = world(medicines=False)
    assert run(tools["start_teach_back"](Script()))["speakable"].startswith("There's nothing in your plan to check yet.")


def test_a_family_member_cannot_start_a_teach_back() -> None:
    _clock, service, deps, tools, _items = world()
    invitation = service.invite(PATIENT, ["read_tasks", "perform_tasks"], name="Sam")
    service.accept_invitation(SAM, invitation["id"])
    deps.local_identity = SAM
    with pytest.raises(ToolError, match="Teach-back is unavailable"):
        run(tools["start_teach_back"](Script(*ALL_RIGHT)))
    with pytest.raises(AccessDenied):
        service.teach_back_results(SAM)


def test_a_host_without_elicitation_gets_a_clear_error() -> None:
    _clock, _service, _deps, tools, _items = world()

    class NoElicitation:
        headers = None

        async def elicit(self, message, schema):
            raise RuntimeError("client does not support elicitation")

    with pytest.raises(ToolError, match="Teach-back is unavailable"):
        run(tools["start_teach_back"](NoElicitation()))


# ---- what is kept, and who sees it ------------------------------------------------------------------
def test_only_the_structured_value_is_kept_never_the_words() -> None:
    _clock, service, _deps, tools, _items = world()
    run(tools["start_teach_back"](Script("I take it twice a day with my tea", "every 12 hours with toast", "stop")))
    stored = json.dumps(service.storage.list("demo-patient", "TEACH_BACK"))
    assert "tea" not in stored and "toast" not in stored and '"every_hours": 12' in stored


def test_results_are_exported_deleted_with_everything_else_and_never_listed_for_family() -> None:
    _clock, service, _deps, tools, _items = world()
    run(tools["start_teach_back"](Script(*ALL_RIGHT)))
    assert sum(r["type"] == "TEACH_BACK" for r in service.export(PATIENT)["records"]) == 6
    invitation = service.invite(PATIENT, ["read_tasks", "read_observations"], name="Sam")
    service.accept_invitation(SAM, invitation["id"])
    assert not any(r["type"] == "TEACH_BACK" for r in service.list_records(SAM))
    with pytest.raises(AccessDenied):
        service.list_records(SAM, "TEACH_BACK")
    service.delete_all(PATIENT)
    assert service.storage.list("demo-patient", "TEACH_BACK") == []


def test_the_latest_result_wins_and_an_item_taken_out_of_the_plan_drops_out() -> None:
    clock, service, _deps, tools, items = world()
    run(tools["start_teach_back"](Script("I don't know", "stop")))
    clock[0] += 60
    service.save_workflow(PATIENT, service.active_workflow(PATIENT, "teach_back") | {"status": "done"})
    run(tools["start_teach_back"](Script(*ALL_RIGHT)))
    latest = {(r["item_id"], r["check"]): r["result"] for r in service.teach_back_results(PATIENT)}
    assert latest[(items["amoxicillin"]["id"], "frequency")] == "understood"
    service.delete(PATIENT, items["fever"]["id"])
    assert (items["fever"]["id"], "number") not in {(r["item_id"], r["check"]) for r in service.teach_back_results(PATIENT)}


# ---- the handoff and suggestions ---------------------------------------------------------------------
def test_the_handoff_shows_the_latest_result_for_each_checked_value_with_its_lines() -> None:
    _clock, service, _deps, tools, items = world()
    run(tools["start_teach_back"](Script("I don't know", *ALL_RIGHT[1:])))
    handoff = service.create_visit_handoff(PATIENT, NOW - 86_400, NOW + 60)
    totals = handoff["totals"]
    assert (totals["understood"], totals["needs_clarification"], totals["checkable"]) == (5, 1, 6)
    (amoxicillin,) = [u for u in handoff["understanding"] if u["item_id"] == items["amoxicillin"]["id"]]
    assert amoxicillin["result"] == "needs_clarification" and amoxicillin["question"] == "How often do you take Amoxicillin?"
    assert [e["line_id"] for e in amoxicillin["source_citation"]["page_excerpts"]] == ["p1:L3"]


def test_the_suggestion_asks_for_a_first_check_then_another_look_then_goes_away() -> None:
    _clock, service, _deps, tools, items = world()
    (due,) = [s for s in service.suggestions(PATIENT) if s["kind"] == "teach_back_due"]
    assert due["say"] == "You haven't checked your understanding of your plan."
    assert due["offer"] == {"say": "Want to do that now?", "tool": "start_teach_back", "arguments": {}}
    assert due["source"] == {"type": "PLAN_TASK", "id": items["amoxicillin"]["id"]}
    run(tools["start_teach_back"](Script("I don't know", *ALL_RIGHT[1:])))
    (due,) = [s for s in service.suggestions(PATIENT) if s["kind"] == "teach_back_due"]
    assert due["say"] == "Part of your plan needs another look."
    run(tools["start_teach_back"](Script(*ALL_RIGHT)))
    assert "teach_back_due" not in [s["kind"] for s in service.suggestions(PATIENT)]


def test_the_teach_back_suggestion_comes_last_and_never_pushes_out_the_others() -> None:
    _clock, service, _deps, _tools, _items = world()
    service.write(PATIENT, "PLAN_NOTE", {"item_kind": "appointment", "label": "Visit", "status": "active",
                                         "text": "Follow-up on 2026-10-17.", "due_date": "2026-10-17"}, reviewed=True)
    service.intake_text_document(PATIENT, "New plan", "TASK: Drink water | schedule: morning")
    assert [s["kind"] for s in service.suggestions(PATIENT)] == ["visit_soon", "review_waiting", "teach_back_due"]


def test_the_pattern_fallback_names_the_medicine_not_the_list_number() -> None:
    from care_loop.structuring.validate import pattern_extraction
    from care_loop.extraction import SourceLine
    line = SourceLine(page=1, number=5, text="1. Amoxicillin 500 mg capsule: Take 1 capsule by mouth three times daily.",
                      method="text", confidence_pct=100)
    (item,) = pattern_extraction([line]).items
    assert item.medication.name == "Amoxicillin"


def test_the_read_back_leaves_out_the_documents_list_numbering() -> None:
    clock, service, _deps, tools, items = world()
    amoxicillin = service.storage.get("demo-patient", items["amoxicillin"]["id"])
    service.storage.put("demo-patient", amoxicillin["id"], "PLAN_TASK", amoxicillin | {"text": "1. " + amoxicillin["text"]})
    person = Script("I don't know", "stop")
    run(tools["start_teach_back"](person))
    assert person.asked[1].startswith("That's okay. Your plan says: Amoxicillin 500 mg")
