"""Multi-turn workflows: chained check-in questions, guided voice review with pause/resume,
next-step offers, and rescheduling by spoken time."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from care_loop.auth import Identity
from care_loop.core import CareLoopService, resolve_spoken_time
from care_loop.storage import CareLoopStorage
from care_loop.tools.records import register

PATIENT = Identity("demo-patient", "patient", "demo-patient")
SAM = Identity("demo-caregiver", "caregiver", "demo-patient")
PLAN = "\n".join(["TASK: Take a short walk | schedule: morning",
                  "TASK: Change the dressing | schedule: evening",
                  "RULE: PAIN_SCORE_AT_OR_ABOVE threshold=7 consecutive_days=2"])
NOW = int(datetime(2026, 10, 16, 18, 0, tzinfo=UTC).timestamp())


class FakeMCP:
    def __init__(self) -> None:
        self.tools = {}

    def tool(self, *, name, annotations=None, meta=None):
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
    """A scripted person answering MCP elicitations, in order."""

    def __init__(self, *answers) -> None:
        self.answers, self.asked = list(answers), []
        self.headers = None

    async def elicit(self, message, schema):
        self.asked.append(message)
        answer = self.answers.pop(0)
        if isinstance(answer, str):
            return type("Reply", (), {"action": answer})()
        return type("Reply", (), {"action": "accept", "data": schema(**answer)})()


def setup(*, invite_sam=True, approve=False):
    clock = [NOW]
    service = CareLoopService(CareLoopStorage(":memory:", clock=lambda: clock[0]), clock=lambda: clock[0], timezone="UTC")
    deps = Deps(service)
    mcp = FakeMCP()
    register(mcp, deps)
    if invite_sam:
        invitation = service.invite(PATIENT, ["read_tasks", "perform_tasks"], name="Sam")
        service.accept_invitation(SAM, invitation["id"])
    imported = mcp.tools["import_care_plan_text"]("Synthetic plan", PLAN, Script())
    if approve:
        for draft in service.list_care_tasks(PATIENT):
            service.approve_plan_item(PATIENT, draft["id"])
    return clock, service, deps, mcp.tools, imported


def run(coroutine):
    return asyncio.run(coroutine)


def tasks_by_schedule(service):
    return {t["schedule"]: t for t in service.list_care_tasks(PATIENT) if t["type"] == "PLAN_TASK"}


# ---- spoken times ------------------------------------------------------------------------------
@pytest.mark.parametrize(("spoken", "reference", "expected"), [
    ("make it 9", ["19:00"], "21:00"), ("make it 9", ["08:00"], "09:00"), ("8 pm", None, "20:00"),
    ("20:30", None, "20:30"), ("nine", ["21:00"], "21:00"), ("7:30 am", ["19:00"], "07:30")])
def test_resolve_spoken_time(spoken, reference, expected) -> None:
    assert resolve_spoken_time(spoken, reference) == expected


def test_resolve_spoken_time_rejects_nonsense() -> None:
    with pytest.raises(ValueError):
        resolve_spoken_time("whenever")


# ---- next-step offers ------------------------------------------------------------------------------
def test_import_offers_a_voice_review() -> None:
    _clock, _service, _deps, _tools, imported = setup()
    assert imported["next_step"] == {"say": "Want to go through them now?", "tool": "review_plan_by_voice", "arguments": {}}
    assert imported["speakable"].endswith("Want to go through them now?")


def test_approving_the_last_draft_offers_to_assign_an_evening_task() -> None:
    _clock, service, _deps, tools, _imported = setup()
    drafts = service.voice_reviewable(PATIENT)[0]
    for draft in drafts[:-1]:
        assert "next_step" not in tools["approve_plan_item"](draft["id"], Script())  # still reviewing
    last = tools["approve_plan_item"](drafts[-1]["id"], Script())
    evening = tasks_by_schedule(service)["evening"]
    assert last["next_step"]["tool"] == "assign_task"
    assert last["next_step"]["arguments"]["task"] == evening["id"]
    assert last["next_step"]["say"] == "Want Sam to handle Change the dressing?"


# ---- guided review with pause and resume -------------------------------------------------------------
def test_guided_review_changes_time_assigns_pauses_and_resumes() -> None:
    _clock, service, _deps, tools, _imported = setup()
    first = Script({"new_time": "9"}, {"who": "Sam"}, "decline")
    paused = run(tools["review_plan_by_voice"](first))
    assert first.asked[0] == ("Item 1 of 3: Take a short walk, at 8 AM. Approve, change the time, "
                              "give it to someone, skip, or stop?")
    assert first.asked[2].startswith("Item 3 of 3: Alert rule: contact your clinic when your pain score is 7 or higher")
    assert first.asked[2].endswith("Approve, skip, or stop?")
    assert paused["speakable"] == 'Okay, I\'ve saved your place. 1 item left. Say "continue my review" anytime.'

    tasks = tasks_by_schedule(service)
    assert tasks["morning"]["status"] == "active" and tasks["morning"]["times"] == ["09:00"]
    assert tasks["evening"]["status"] == "active" and tasks["evening"]["assignee_name"] == "Sam"

    resume = Script({"action": "approve"})
    done = run(tools["review_plan_by_voice"](resume))
    assert resume.asked[0].startswith("Item 3 of 3:")
    assert done["speakable"] == "Done: 3 approved."
    assert "next_step" not in done  # Sam was already given a task during the review
    assert {r["label"] for r in done["reminders"]} == {"Take a short walk", "Change the dressing"}
    assert service.active_workflow(PATIENT, "plan_review") is None


def test_unclear_answer_is_asked_again_then_skip_and_offer() -> None:
    _clock, service, _deps, tools, _imported = setup()
    person = Script({}, {"action": "skip"}, {"action": "approve"}, {"action": "approve"})
    done = run(tools["review_plan_by_voice"](person))
    assert person.asked[1].startswith("Sorry, I didn't catch that.")
    assert done["speakable"] == "Done: 2 approved, 1 skipped. Want Sam to handle Change the dressing?"
    assert done["next_step"]["tool"] == "assign_task"  # nobody was given a task yet
    assert tasks_by_schedule(service)["morning"]["status"] == "draft"


def test_medicine_and_flagged_items_stay_on_screen() -> None:
    _clock, service, _deps, tools, _imported = setup()
    for draft in service.list_care_tasks(PATIENT):
        service.storage.put("demo-patient", draft["id"], draft["type"], draft | {"item_kind": "medication_task"})
    result = run(tools["review_plan_by_voice"](Script()))
    assert result["speakable"] == "There's nothing to review by voice. 3 items are waiting on your screen."


# ---- chained check-in -------------------------------------------------------------------------------
def test_checkin_asks_about_own_tasks_and_mentions_family_tasks() -> None:
    _clock, service, _deps, tools, _imported = setup(approve=True)
    tasks = tasks_by_schedule(service)
    grant = service.list_grants(PATIENT)[0]
    service.assign_task(PATIENT, tasks["evening"]["id"], grant["id"])
    person = Script({"pain_score": 4}, {"done": True})
    result = run(tools["start_daily_checkin"](person))
    assert person.asked == ["On a scale from 0 to 10, what's your pain score today?", "Did you do Take a short walk today?"]
    assert result["speakable"] == "Check-in recorded. You did 1 of 1 task. Sam has Change the dressing at 7 PM."
    assert "4" not in result["speakable"]
    events = service.storage.list("demo-patient", "TASK_EVENT")
    assert [e["task_id"] for e in events] == [tasks["morning"]["id"]]


def test_checkin_stopped_midway_keeps_the_answers() -> None:
    _clock, service, _deps, tools, _imported = setup(invite_sam=False, approve=True)
    person = Script({"pain_score": 6}, {"done": False}, "cancel")
    result = run(tools["start_daily_checkin"](person))
    assert result["speakable"] == "Check-in recorded. You did 0 of 1 task. Take a short walk is still to do. I saved what you told me."
    assert service.list_observations(PATIENT)[0]["pain_score"] == 6


# ---- rescheduling ------------------------------------------------------------------------------------
def test_update_task_time_by_spoken_time() -> None:
    _clock, service, _deps, tools, _imported = setup(approve=True)
    evening = tasks_by_schedule(service)["evening"]
    moved = tools["update_task_time"](evening["id"], "8 pm", Script())
    assert moved["speakable"] == "Done. Change the dressing is now at 8 PM."
    assert moved["reminders"][0]["times"] == ["20:00"]
    assert service.storage.get("demo-patient", evening["id"])["edits"][-1]["to"] == ["20:00"]
    with pytest.raises(ToolError):
        tools["update_task_time"](evening["id"], "whenever", Script())


def test_tasks_and_people_can_be_named_instead_of_ids() -> None:
    _clock, service, _deps, tools, _imported = setup(approve=True)
    assigned = tools["assign_task"]("the dressing", Script(), "Sam")
    assert assigned["speakable"] == "Done. Sam will handle Change the dressing at 7 PM."
    moved = tools["update_task_time"]("the walk", "10", Script())
    assert moved["speakable"] == "Done. Take a short walk is now at 10 AM."
    with pytest.raises(ToolError):
        tools["assign_task"]("the", Script(), "Sam")  # says nothing about which task
    with pytest.raises(ToolError):
        tools["assign_task"]("swimming", Script(), "Sam")  # matches no task
    with pytest.raises(ToolError):
        tools["assign_task"]("the walk", Script(), "Nobody")


def test_checkin_groups_family_tasks_by_person() -> None:
    _clock, service, _deps, tools, _imported = setup(approve=True)
    tools["assign_task"]("walk", Script(), "Sam")
    tools["assign_task"]("dressing", Script(), "Sam")
    result = run(tools["start_daily_checkin"](Script({"pain_score": 3})))
    assert result["speakable"] == "Check-in recorded. Sam has Take a short walk at 8 AM and Change the dressing at 7 PM."


def test_document_lines_are_read_without_doubled_punctuation() -> None:
    _clock, _service, _deps, tools, _imported = setup(invite_sam=False)
    tools["import_care_plan_text"]("Typed", "TASK: Change the wound dressing every evening. | schedule: evening", Script())
    person = Script({"action": "approve"}, {"action": "approve"}, {"action": "approve"}, "decline")
    run(tools["review_plan_by_voice"](person))
    assert any("Change the wound dressing every evening, at 7 PM." in q for q in person.asked)
    assert not any(".," in q or ".." in q for q in person.asked)


def test_change_time_without_a_time_asks_what_time() -> None:
    _clock, service, _deps, tools, _imported = setup(invite_sam=False)
    person = Script({"action": "change time"}, {"new_time": "7"}, "decline")
    run(tools["review_plan_by_voice"](person))
    assert person.asked[1] == "What time should it be?"
    assert tasks_by_schedule(service)["morning"]["times"] == ["07:00"]


def test_a_paused_review_picks_up_items_imported_later() -> None:
    _clock, service, _deps, tools, _imported = setup(invite_sam=False)
    run(tools["review_plan_by_voice"](Script({"action": "approve"}, "decline")))  # item 1 done, paused at 2
    tools["import_care_plan_text"]("Second plan", "TASK: Drink water | schedule: lunchtime", Script())
    person = Script({"action": "approve"}, {"action": "approve"}, {"action": "approve"})
    done = run(tools["review_plan_by_voice"](person))
    assert person.asked[0].startswith("Item 2 of 4:") and person.asked[2].startswith("Item 4 of 4: Drink water, at noon.")
    assert done["speakable"] == "Done: 4 approved."
