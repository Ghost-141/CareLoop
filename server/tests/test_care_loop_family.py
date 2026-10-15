"""Items 7–10: plain 401 for Alexa+, family task assignment with reminders and missed tasks,
questions for the clinician, and who-accessed-my-data."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from mcp.server.mcpserver.exceptions import ToolError

from care_loop.auth import Identity, TokenAuth
from care_loop.config import Settings
from care_loop.core import AccessDenied, CareLoopService
from care_loop.server import build_deps, create_app
from care_loop.storage import CareLoopStorage
from care_loop.tools.records import register

PATIENT = Identity("demo-patient", "patient", "demo-patient")
SAM = Identity("demo-caregiver", "caregiver", "demo-patient")
PLAN = "TASK: Take a short walk | schedule: morning\nTASK: Change the dressing | schedule: evening"
DAY = datetime(2026, 10, 16, tzinfo=UTC)


def at(hour: int, minute: int = 0) -> int:
    return int(DAY.replace(hour=hour, minute=minute).timestamp())


class FakeMCP:
    def __init__(self) -> None:
        self.tools = {}

    def tool(self, *, name, annotations=None, meta=None):
        def register_tool(fn):
            self.tools[name] = fn
            return fn
        return register_tool


class Ctx:
    headers = None


class Deps:
    def __init__(self, service: CareLoopService) -> None:
        self.service, self.local_identity = service, PATIENT

    def identity(self, _ctx):
        return self.local_identity


def setup(scopes=("read_tasks", "perform_tasks", "receive_alerts")):
    clock = [at(7)]
    service = CareLoopService(CareLoopStorage(":memory:", clock=lambda: clock[0]), clock=lambda: clock[0], timezone="UTC")
    deps = Deps(service)
    mcp = FakeMCP()
    register(mcp, deps)
    for draft in service.intake_text_document(PATIENT, "Synthetic plan", PLAN)["drafts"]:
        service.approve_plan_item(PATIENT, draft["id"])
    invitation = service.invite(PATIENT, list(scopes), name="Sam")
    service.accept_invitation(SAM, invitation["id"])
    tasks = {t["schedule"]: t for t in service.list_care_tasks(PATIENT)}
    return clock, service, deps, mcp.tools, invitation, tasks


# ---- 7: Alexa+ wants a plain 401 -------------------------------------------------------------------
def test_mcp_401_has_no_www_authenticate_header(tmp_path) -> None:
    deps = build_deps(Settings(db_path=str(tmp_path / "x.db"), intake_llm="none", intake_ocr="none"),
                      auth=TokenAuth({"p": PATIENT}))
    with TestClient(create_app(deps)) as client:
        response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert response.status_code == 401
    assert "www-authenticate" not in {k.lower() for k in response.headers}


# ---- 8: family task assignment, reminders, missed tasks ---------------------------------------------
def test_plan_tasks_get_suggested_times_from_schedule_words() -> None:
    _clock, _service, _deps, _tools, _inv, tasks = setup()
    assert tasks["morning"]["times"] == ["08:00"] and tasks["evening"]["times"] == ["19:00"]


def test_patient_assigns_a_task_and_alexa_gets_reminder_suggestions() -> None:
    _clock, service, deps, tools, invitation, tasks = setup()
    circle = tools["list_care_circle"](Ctx())
    assert circle["refs"][0]["name"] == "Sam" and "perform_tasks" in circle["refs"][0]["scopes"]

    result = tools["assign_task"](tasks["evening"]["id"], Ctx(), invitation["id"])
    assert result["speakable"] == "Done. Sam will handle Change the dressing at 7 PM."
    assert result["reminders"] == [{"task_id": tasks["evening"]["id"], "label": "Change the dressing",
                                    "times": ["19:00"], "to": "Sam"}]
    assert result["refs"][0]["assignee"] == "Sam"

    deps.local_identity = SAM
    mine = tools["list_my_assigned_tasks"](Ctx())
    assert mine["speakable"] == "You have 1 task to help the patient with: Change the dressing at 7 PM."
    assert "text" not in service.assigned_tasks(SAM)[0]  # never the cited instruction

    with pytest.raises(ToolError):  # not assigned to Sam
        tools["record_task_completion"](tasks["morning"]["id"], Ctx())
    done = tools["record_task_completion"](tasks["evening"]["id"], Ctx())
    assert done["speakable"] == "Thanks. I've recorded that you did it."
    event = next(e for e in service.storage.list("demo-patient", "TASK_EVENT"))
    assert event["completed_by"] == "demo-caregiver" and event["completed_by_name"] == "Sam"

    deps.local_identity = PATIENT
    back = tools["assign_task"](tasks["evening"]["id"], Ctx())
    assert back["speakable"].startswith("Done. You'll handle Change the dressing yourself.")
    assert back["reminders"][0]["to"] == "patient"


def test_assignment_needs_the_perform_tasks_permission() -> None:
    _clock, service, _deps, tools, invitation, tasks = setup(scopes=("read_tasks",))
    with pytest.raises(ToolError, match="can't be assigned"):
        tools["assign_task"](tasks["evening"]["id"], Ctx(), invitation["id"])
    with pytest.raises(AccessDenied):
        service.assigned_tasks(SAM)


def test_missed_assigned_task_raises_one_generic_update_and_survives_rule_cleanup() -> None:
    clock, service, _deps, tools, invitation, tasks = setup()
    tools["assign_task"](tasks["morning"]["id"], Ctx(), invitation["id"])  # assigned at 7 AM for 08:00
    clock[0] = at(8, 30)
    assert service.notifications(SAM) == []  # still inside the one-hour grace period
    clock[0] = at(9, 5)
    updates = service.notifications(SAM)
    assert len(updates) == 1 and set(updates[0]) == {"case_id", "status"}
    assert service.notifications(SAM) == updates  # one alert per missed slot, not one per check
    service.record_observation(PATIENT, pain_score=2, idempotency_key="k1")  # runs pain-rule cleanup
    assert len(service.notifications(SAM)) == 1

    handoff = service.create_visit_handoff(PATIENT, at(0), at(23))
    assert handoff["totals"]["missed_tasks"] == 1
    assert next(a for a in handoff["alerts"] if a.get("kind") == "missed_task")["task_label"] == "Take a short walk"


def test_a_task_done_on_time_is_not_missed() -> None:
    clock, service, deps, tools, invitation, tasks = setup()
    tools["assign_task"](tasks["morning"]["id"], Ctx(), invitation["id"])
    clock[0] = at(8, 10)
    deps.local_identity = SAM
    tools["record_task_completion"](tasks["morning"]["id"], Ctx())
    clock[0] = at(10)
    assert service.notifications(SAM) == []


# ---- 9: questions for the clinician -----------------------------------------------------------------
def test_questions_are_saved_never_answered_and_reach_the_handoff() -> None:
    clock, service, _deps, tools, _inv, _tasks = setup()
    first = tools["add_question_for_clinician"]("Can I stop my medicine early?", Ctx())
    assert first["speakable"] == "Saved. You have 1 question ready for your next appointment."
    assert "medicine" not in first["speakable"].lower()  # never repeated aloud
    tools["add_question_for_clinician"]("Can I start swimming?", Ctx())
    result = tools["create_visit_handoff"]("last_7_days", Ctx())
    assert result["speakable"].endswith("It includes 2 questions for your clinician.")
    handoff = service.storage.get("demo-patient", result["refs"][0]["id"])
    assert [q["text"] for q in handoff["questions"]] == ["Can I stop my medicine early?", "Can I start swimming?"]
    with pytest.raises(ToolError):
        tools["add_question_for_clinician"]("x" * 301, Ctx())


# ---- 10: who has seen my data ---------------------------------------------------------------------------
def test_patient_hears_who_accessed_their_data() -> None:
    _clock, service, deps, tools, _inv, _tasks = setup()
    assert tools["who_accessed_my_care_data"](Ctx())["speakable"].startswith("In the last 7 days, Sam accepted your invitation")
    deps.local_identity = SAM
    tools["list_care_tasks"](Ctx())
    tools["list_care_tasks"](Ctx())
    service.notifications(SAM)  # generic update checks are not "viewing"
    deps.local_identity = PATIENT
    spoken = tools["who_accessed_my_care_data"](Ctx())["speakable"]
    assert spoken == "In the last 7 days, Sam viewed your tasks 2 times and accepted your invitation."
    deps.local_identity = SAM
    with pytest.raises(ToolError):
        tools["who_accessed_my_care_data"](Ctx())


def test_nobody_else_and_custom_range() -> None:
    clock = [at(7)]
    service = CareLoopService(CareLoopStorage(":memory:", clock=lambda: clock[0]), clock=lambda: clock[0], timezone="UTC")
    mcp = FakeMCP()
    register(mcp, Deps(service))
    assert mcp.tools["who_accessed_my_care_data"](Ctx())["speakable"] == "No one else accessed your care data in the last 7 days."


# ---- clearer refusals (from a live session where the model invented inputs) ---------------------
def test_family_member_without_access_is_told_why() -> None:
    clock = [at(7)]
    service = CareLoopService(CareLoopStorage(":memory:", clock=lambda: clock[0]), clock=lambda: clock[0], timezone="UTC")
    deps = Deps(service)
    deps.local_identity = SAM
    mcp = FakeMCP()
    register(mcp, deps)
    for name in ("list_my_assigned_tasks", "list_generic_notifications"):
        with pytest.raises(ToolError, match="You don't have access to the patient's CareLoop right now"):
            mcp.tools[name](Ctx())


def test_invitation_by_number_of_days_and_past_dates_are_explained() -> None:
    clock = [at(7)]
    service = CareLoopService(CareLoopStorage(":memory:", clock=lambda: clock[0]), clock=lambda: clock[0], timezone="UTC")
    mcp = FakeMCP()
    register(mcp, Deps(service))
    invited = asyncio.run(mcp.tools["invite_caregiver"](["read_tasks"], Ctx(), name="Sam", expires_in_days=14))
    assert invited["speakable"] == "Invitation created: Sam can see your tasks, for 14 days."
    assert invited["refs"][0]["expires_at"] == at(7) + 14 * 86_400
    with pytest.raises(ToolError, match="That expiry date is in the past"):
        asyncio.run(mcp.tools["invite_caregiver"](["read_tasks"], Ctx(), 1735689600))  # 2025-01-01


def test_import_refuses_text_without_plan_instructions() -> None:
    clock = [at(7)]
    service = CareLoopService(CareLoopStorage(":memory:", clock=lambda: clock[0]), clock=lambda: clock[0], timezone="UTC")
    mcp = FakeMCP()
    register(mcp, Deps(service))
    with pytest.raises(ToolError, match="Share the document in the Alexa app"):
        mcp.tools["import_care_plan_text"]("New Care Plan from Clinic", "User's new care plan text from their clinic visit", Ctx())
    assert service.storage.list("demo-patient", "DOCUMENT") == []
