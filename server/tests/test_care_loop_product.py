"""Product readiness: data-use consent, patient profile, crisis redirect, spoken times, legal pages."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from mcp.server.mcpserver.exceptions import ToolError

from care_loop.auth import Identity, TokenAuth
from care_loop.config import Settings
from care_loop.core import CareLoopService
from care_loop.server import INSTRUCTIONS, build_deps, create_app
from care_loop.storage import CareLoopStorage
from care_loop.tools.records import _say_time, register

PATIENT = Identity("demo-patient", "patient", "demo-patient")
SAM = Identity("demo-caregiver", "caregiver", "demo-patient")
NOW = int(datetime(2026, 10, 16, 7, 0, tzinfo=UTC).timestamp())


class FakeMCP:
    def __init__(self) -> None:
        self.tools = {}

    def tool(self, *, name, title=None, annotations=None, meta=None):
        def register_tool(fn):
            self.tools[name] = fn
            return fn
        return register_tool


class Ctx:
    headers = None


class Deps:
    def __init__(self, service):
        self.service, self.local_identity = service, PATIENT

    def identity(self, _ctx):
        return self.local_identity


def setup(require_consent=True):
    service = CareLoopService(CareLoopStorage(":memory:", clock=lambda: NOW), clock=lambda: NOW, timezone="UTC",
                              require_consent=require_consent, default_patient_name="Maya")
    deps = Deps(service)
    mcp = FakeMCP()
    register(mcp, deps)
    return service, deps, mcp.tools


@pytest.mark.parametrize(("value", "spoken"), [("19:00", "7 PM"), ("08:30", "8:30 AM"), ("12:00", "noon"),
                                               ("00:00", "midnight"), ("21:15", "9:15 PM"), ("bad", "bad")])
def test_times_are_spoken_naturally(value, spoken) -> None:
    assert _say_time(value) == spoken


def test_patient_hears_the_data_use_disclosure_once_before_anything_is_stored() -> None:
    service, deps, tools = setup()
    first = tools["list_care_tasks"](Ctx())
    assert first["speakable"].startswith("Before I save anything: CareLoop keeps your care plan")
    assert first["speakable"].endswith("Is that okay?")
    assert first["next_step"] == {"say": "Is that okay?", "tool": "accept_data_use", "arguments": {}, "retry": True}
    assert service.storage.list("demo-patient") == []  # nothing stored before consent
    assert tools["accept_data_use"](Ctx())["speakable"] == "Thanks, you're all set."
    assert service.has_consented("demo-patient")
    assert tools["list_care_tasks"](Ctx())["speakable"] == "You have no CareLoop plan items yet."


def test_family_members_are_not_asked_for_the_patients_consent() -> None:
    service, deps, tools = setup()
    deps.local_identity = SAM
    with pytest.raises(ToolError, match="You don't have access"):
        tools["list_my_assigned_tasks"](Ctx())  # their own access rules apply, not the disclosure


def test_profile_name_and_time_zone() -> None:
    service, deps, tools = setup(require_consent=False)
    done = tools["set_my_details"](Ctx(), name="Maya", timezone="Asia/Dhaka")
    assert done["speakable"] == "Done. I'll call you Maya and times now follow Asia/Dhaka."
    assert service.patient_name("demo-patient") == "Maya"
    assert str(service._zone("demo-patient")) == "Asia/Dhaka"
    with pytest.raises(ToolError):
        tools["set_my_details"](Ctx(), timezone="Mars/Olympus")
    with pytest.raises(ToolError):
        tools["set_my_details"](Ctx(), name="<script>")


def test_family_messages_use_the_patients_name() -> None:
    service, deps, tools = setup(require_consent=False)
    service.update_profile(PATIENT, name="Maya")
    invitation = service.invite(PATIENT, ["read_tasks", "perform_tasks"], name="Sam")
    service.accept_invitation(SAM, invitation["id"])
    deps.local_identity = SAM
    assert tools["list_my_assigned_tasks"](Ctx())["speakable"] == "You don't have any CareLoop tasks to help Maya with."


def test_crisis_words_are_redirected_and_never_filed_as_questions() -> None:
    service, deps, tools = setup(require_consent=False)
    reply = tools["add_question_for_clinician"]("Is it normal that I want to end my life?", Ctx())
    assert "call your local emergency number" in reply["speakable"] and "988" in reply["speakable"]
    assert service.storage.list("demo-patient", "QUESTION") == []
    assert "988" in INSTRUCTIONS


def test_privacy_and_terms_pages_are_public(tmp_path) -> None:
    deps = build_deps(Settings(db_path=str(tmp_path / "x.db"), intake_llm="none", intake_ocr="none"),
                      auth=TokenAuth({"p": PATIENT}))
    with TestClient(create_app(deps)) as client:
        privacy, terms = client.get("/privacy"), client.get("/terms")
    assert privacy.status_code == 200 and "What CareLoop keeps" in privacy.text and "24 hours" in privacy.text
    assert terms.status_code == 200 and "not an emergency service" in terms.text and "MIT License" in terms.text


def test_server_turns_consent_on_by_default_and_uses_configured_name(tmp_path) -> None:
    deps = build_deps(Settings(db_path=str(tmp_path / "x.db"), intake_llm="none", intake_ocr="none",
                               patient_name="Maya", timezone="Asia/Dhaka"), auth=TokenAuth({"p": PATIENT}))
    assert deps.service.require_consent is True
    assert deps.service.patient_name("demo-patient") == "Maya"
    assert str(deps.service._zone("demo-patient")) == "Asia/Dhaka"


def test_patient_asking_my_tasks_through_the_family_tool_gets_their_own_plan() -> None:
    service, deps, tools = setup(require_consent=False)
    assert tools["list_my_assigned_tasks"](Ctx())["speakable"] == "You have no CareLoop plan items yet."
