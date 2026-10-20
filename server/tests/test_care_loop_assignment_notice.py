"""A family member is told when a task is assigned to them. The notice names nothing; details come when they ask."""
from __future__ import annotations

import json

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from care_loop.auth import Identity
from care_loop.core import ASSIGNMENT_NOTICE_TTL_SECONDS, AccessDenied
from test_care_loop_family import PATIENT, SAM, Ctx, at, setup

ALEX = Identity("alex-caregiver", "caregiver", "demo-patient")


def as_sam(deps) -> None:
    deps.local_identity = SAM


def assign(tools, deps, tasks, invitation, which="evening") -> None:
    deps.local_identity = PATIENT
    tools["assign_task"](tasks[which]["id"], Ctx(), invitation["id"])
    as_sam(deps)


def notices(service, who=SAM):
    return [row for row in service.notifications(who) if row.get("kind") == "task_assigned"]


def test_assigning_a_task_creates_one_generic_notice_for_the_assignee_only() -> None:
    clock, service, deps, tools, invitation, tasks = setup()
    assign(tools, deps, tasks, invitation)
    rows = notices(service)
    assert len(rows) == 1 and rows[0]["status"] == "action_required" and set(rows[0]) == {"case_id", "status", "kind"}
    assert "dressing" not in json.dumps(rows).lower()  # no task name, time or content in the notice
    other = service.invite(PATIENT, ["read_tasks", "perform_tasks"], name="Alex")
    service.accept_invitation(ALEX, other["id"])
    assert notices(service, ALEX) == []  # addressed to Sam only
    with pytest.raises(AccessDenied):
        service.notifications(PATIENT)


def test_a_helper_invited_to_do_tasks_without_alert_permission_still_gets_the_notice() -> None:
    """"let Sam help with my tasks" grants see-tasks and do-tasks, not receive_alerts."""
    clock, service, deps, tools, invitation, tasks = setup(scopes=("read_tasks", "perform_tasks"))
    assign(tools, deps, tasks, invitation)
    assert len(notices(service)) == 1
    clock[0] = at(21)
    assert [r for r in service.notifications(SAM) if r.get("kind") != "task_assigned"] == []  # alerts need their own permission


def test_someone_who_can_neither_receive_alerts_nor_do_tasks_gets_nothing() -> None:
    clock, service, deps, tools, invitation, tasks = setup(scopes=("read_tasks",))
    with pytest.raises(AccessDenied):
        service.notifications(SAM)


def test_new_task_wording_is_counts_only() -> None:
    clock, service, deps, tools, invitation, tasks = setup()
    service.default_patient_name = "Maya"
    assign(tools, deps, tasks, invitation)
    result = tools["list_generic_notifications"](Ctx())
    assert result["speakable"] == "You have 1 new task from Maya."
    assert [r["kind"] for r in result["refs"]] == ["assigned_task"] and result["refs"][0]["label"] == "new task 1"
    assert "dressing" not in json.dumps(result).lower()

    deps.local_identity = PATIENT
    tools["assign_task"](tasks["morning"]["id"], Ctx(), invitation["id"])
    as_sam(deps)
    assert tools["list_generic_notifications"](Ctx())["speakable"] == "You have 2 new tasks from Maya."
    clock[0] = at(9, 5)  # the morning task is now missed, which is a real update
    both = tools["list_generic_notifications"](Ctx())["speakable"]
    assert both == "You have 1 new CareLoop update and 2 new tasks from Maya."
    assert "walk" not in both.lower()


def test_asking_for_your_tasks_gives_the_detail_and_clears_the_notice() -> None:
    clock, service, deps, tools, invitation, tasks = setup()
    service.default_patient_name = "Maya"
    assign(tools, deps, tasks, invitation)
    detail = tools["list_my_assigned_tasks"](Ctx())
    assert "Change the dressing" in detail["speakable"]
    after = tools["list_generic_notifications"](Ctx())
    assert after["speakable"] == "There are no new CareLoop updates." and after["refs"][0]["status"] == "acknowledged"


def test_mark_it_seen_clears_the_notice_without_the_acknowledge_permission() -> None:
    clock, service, deps, tools, invitation, tasks = setup(scopes=("read_tasks", "perform_tasks"))
    assign(tools, deps, tasks, invitation)
    result = tools["acknowledge_alert"](Ctx())
    assert result["speakable"] == "Marked as seen." and result["refs"][0]["kind"] == "assigned_task"
    assert tools["list_generic_notifications"](Ctx())["speakable"] == "There are no new CareLoop updates."
    with pytest.raises(ToolError, match="can't be acknowledged"):
        tools["acknowledge_alert"](Ctx())  # nothing is waiting any more


def test_a_notice_for_someone_elses_task_cannot_be_acknowledged() -> None:
    clock, service, deps, tools, invitation, tasks = setup()
    assign(tools, deps, tasks, invitation)
    case_id = notices(service)[0]["case_id"]
    other = service.invite(PATIENT, ["read_tasks", "perform_tasks", "acknowledge_alerts"], name="Alex")
    service.accept_invitation(ALEX, other["id"])
    with pytest.raises(AccessDenied):
        service.acknowledge_alert(ALEX, case_id)


def test_the_notice_is_withdrawn_when_the_task_moves_or_is_done() -> None:
    clock, service, deps, tools, invitation, tasks = setup()
    assign(tools, deps, tasks, invitation)
    assert len(notices(service)) == 1
    # reassigned to the same person: one active notice, not two
    assign(tools, deps, tasks, invitation)
    assert len(notices(service)) == 1
    # taken back by the patient
    deps.local_identity = PATIENT
    tools["assign_task"](tasks["evening"]["id"], Ctx())
    assert notices(service) == []
    # assigned again, then completed by Sam before he looked
    assign(tools, deps, tasks, invitation)
    assert len(notices(service)) == 1
    tools["record_task_completion"](tasks["evening"]["id"], Ctx())
    assert notices(service) == []


def test_repeating_the_same_assignment_does_not_notify_again() -> None:
    clock, service, deps, tools, invitation, tasks = setup()
    assign(tools, deps, tasks, invitation)
    first = notices(service)[0]["case_id"]
    tools["list_my_assigned_tasks"](Ctx())  # Sam has seen it
    assign(tools, deps, tasks, invitation)  # Maya says the same thing again
    rows = notices(service)
    assert [r["case_id"] for r in rows] == [first] and rows[0]["status"] == "acknowledged"


def test_reassigning_to_another_person_moves_the_notice() -> None:
    clock, service, deps, tools, invitation, tasks = setup()
    other = service.invite(PATIENT, ["read_tasks", "perform_tasks"], name="Alex")
    service.accept_invitation(ALEX, other["id"])
    assign(tools, deps, tasks, invitation)
    deps.local_identity = PATIENT
    tools["assign_task"](tasks["evening"]["id"], Ctx(), other["id"])
    assert notices(service) == [] and len(notices(service, ALEX)) == 1


def test_the_notice_is_not_a_clinical_alert_in_the_handoff() -> None:
    clock, service, deps, tools, invitation, tasks = setup()
    assign(tools, deps, tasks, invitation)
    handoff = service.create_visit_handoff(PATIENT, at(0), at(23))
    assert handoff["totals"]["alerts"] == 0 and handoff["alerts"] == []


def test_the_notice_expires() -> None:
    clock, service, deps, tools, invitation, tasks = setup()
    assign(tools, deps, tasks, invitation)
    clock[0] += ASSIGNMENT_NOTICE_TTL_SECONDS + 60
    assert notices(service) == []
