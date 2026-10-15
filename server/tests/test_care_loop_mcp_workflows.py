"""MCP adapters: voice-safe results, refs, error signalling, and MCP App views."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from care_loop.auth import Identity
from care_loop.core import CareLoopService
from care_loop.server import INSTRUCTIONS, build_deps, build_server
from care_loop.storage import CareLoopStorage
from care_loop.tools.records import register
from care_loop.ui import VIEWS
from mcp.server.mcpserver.exceptions import ToolError


class FakeMCP:
    def __init__(self) -> None:
        self.tools = {}
        self.meta = {}
        self.annotations = {}

    def tool(self, *, name: str, annotations=None, meta=None):
        def decorator(function):
            self.tools[name] = function
            self.meta[name] = meta
            self.annotations[name] = annotations
            return function
        return decorator


@dataclass
class FakeContext:
    headers: None = None


@dataclass
class Deps:
    service: CareLoopService
    local_identity: Identity

    def identity(self, _ctx: FakeContext) -> Identity:
        return self.local_identity


def build(now: list[int], identity: Identity) -> tuple[FakeMCP, Deps]:
    service = CareLoopService(CareLoopStorage(":memory:", clock=lambda: now[0]), clock=lambda: now[0])
    deps = Deps(service, identity)
    mcp = FakeMCP()
    register(mcp, deps)
    return mcp, deps


def patient() -> Identity:
    return Identity("patient", "patient", "patient")


def caregiver() -> Identity:
    return Identity("caregiver", "caregiver", "patient")


PLAN = "TASK: Take a daily walk | schedule: morning\nRULE: PAIN_SCORE_AT_OR_ABOVE threshold=7 consecutive_days=2"


def assert_voice_contract(result: dict, view: str) -> None:
    assert set(result) - {"reminders", "next_step"} == {"status", "speakable", "surface", "view", "refs"}
    assert result["status"] == "ok"
    assert isinstance(result["speakable"], str) and result["speakable"]
    assert result["surface"] in {"glance", "private_screen"}
    assert result["view"] == f"ui://careloop/{view}"
    for ref in result["refs"]:
        assert {"id", "kind", "label"} <= set(ref)


def test_every_model_tool_declares_an_mcp_app_view_and_annotations() -> None:
    mcp, _deps = build([100], patient())
    for name, meta in mcp.meta.items():
        assert mcp.annotations[name] is not None, name
        ui = meta["ui"]
        if name in {"get_private_view", "review_plan_item"}:
            assert ui == {"visibility": ["app"]}
        else:
            assert ui["resourceUri"].removeprefix("ui://careloop/") in VIEWS, name
    assert mcp.annotations["revoke_caregiver"].destructive_hint is True
    assert mcp.annotations["delete_care_record"].destructive_hint is True
    assert mcp.annotations["list_care_tasks"].read_only_hint is True


def test_voice_approval_flow_uses_refs_without_plan_text() -> None:
    now = [1_791_936_000]
    mcp, deps = build(now, patient())

    imported = mcp.tools["import_care_plan_text"]("Synthetic plan", PLAN, FakeContext())
    assert_voice_contract(imported, "plan-review")
    assert imported["speakable"].startswith("Imported 2 plan items")
    assert "walk" not in str(imported).lower() and "threshold" not in str(imported).lower()
    labels = {ref["label"]: ref["id"] for ref in imported["refs"]}
    assert set(labels) == {"draft task 1", "draft rule 1"}

    for record_id in labels.values():
        assert_voice_contract(mcp.tools["approve_plan_item"](record_id, FakeContext()), "plan-review")
    tasks = mcp.tools["list_care_tasks"](FakeContext())
    assert tasks["speakable"] == "You have 1 active task and 1 active follow-up rule."

    with pytest.raises(ToolError, match="needs your review on screen"):
        mcp.tools["approve_plan_item"](labels["draft task 1"], FakeContext())


def test_care_circle_invite_accept_and_revoke_through_mcp() -> None:
    now = [1_791_936_000]
    mcp, deps = build(now, patient())
    invited = mcp.tools["invite_caregiver"](["read_tasks", "receive_alerts"], FakeContext(), "2026-12-31")
    assert_voice_contract(invited, "care-circle")
    invitation_id = invited["refs"][0]["id"]
    assert invited["refs"][0]["status"] == "pending"

    deps.local_identity = caregiver()
    accepted = mcp.tools["accept_caregiver_invitation"](invitation_id, FakeContext())
    assert accepted["refs"][0]["status"] == "active"

    deps.local_identity = patient()
    circle = mcp.tools["list_care_circle"](FakeContext())
    assert circle["speakable"] == "Your care circle has 1 active caregiver and 0 pending invitations."
    assert_voice_contract(mcp.tools["revoke_caregiver"](invitation_id, FakeContext()), "care-circle")
    assert deps.service.storage.get("patient", invitation_id)["status"] == "revoked"

    with pytest.raises(ToolError, match="can't be revoked"):
        mcp.tools["revoke_caregiver"]("missing", FakeContext())


def test_handoff_accepts_iso_dates_and_relative_ranges() -> None:
    now = [1_791_936_000]
    mcp, deps = build(now, patient())

    iso_result = mcp.tools["create_visit_handoff"]("2026-10-01", FakeContext(), "2026-10-07")
    assert_voice_contract(iso_result, "visit-handoff")
    iso = deps.service.storage.get("patient", iso_result["refs"][0]["id"])
    assert iso["from_date"] == 1_790_812_800
    assert iso["to_date"] == 1_791_417_599

    relative = mcp.tools["create_visit_handoff"]("last_7_days", FakeContext())
    stored = deps.service.storage.get("patient", relative["refs"][0]["id"])
    assert stored["from_date"] == now[0] - 7 * 86_400
    assert stored["to_date"] == now[0]


@pytest.mark.parametrize(
    ("from_date", "to_date"),
    [
        ("not-a-date", "2026-10-07"),
        ("2026-10-07", "not-a-date"),
        ("last_0_days", None),
        ("last_7_days", "2026-10-07"),
    ],
)
def test_handoff_rejects_invalid_iso_and_relative_ranges(from_date: str, to_date: str | None) -> None:
    mcp, _deps = build([1_791_936_000], patient())

    with pytest.raises(ToolError, match="Visit handoff is unavailable"):
        mcp.tools["create_visit_handoff"](from_date, FakeContext(), to_date)


@pytest.mark.parametrize("invalid_expiry", [True, False, "soon", -5])
def test_invite_rejects_invalid_expiry_before_storage(invalid_expiry) -> None:
    mcp, deps = build([100], patient())

    with pytest.raises(ToolError, match="Caregiver invitation is unavailable"):
        mcp.tools["invite_caregiver"](["read_tasks"], FakeContext(), invalid_expiry)
    assert deps.service.storage.list("patient", "CONSENT") == []


def test_generic_notifications_count_and_acknowledge_without_detail() -> None:
    now = [100]
    mcp, deps = build(now, patient())
    deps.service.grant(patient(), "caregiver", ["receive_alerts"])
    deps.local_identity = caregiver()

    none = mcp.tools["list_generic_notifications"](FakeContext())
    assert none["speakable"] == "There are no new CareLoop updates."
    assert none["refs"] == []

    deps.local_identity = patient()
    alert = deps.service.write(patient(), "ALERT", {"text": "pain score 9", "medication": "synthetic"})
    deps.local_identity = caregiver()
    notifications = mcp.tools["list_generic_notifications"](FakeContext())
    assert_voice_contract(notifications, "notifications")
    assert notifications["surface"] == "glance"
    assert notifications["speakable"] == "You have 1 new CareLoop update."
    assert notifications["refs"][0]["id"] == alert["id"]
    assert "pain" not in str(notifications).lower() and "medication" not in str(notifications).lower()

    with pytest.raises(ToolError, match="can't be acknowledged"):
        mcp.tools["acknowledge_alert"](alert["id"], FakeContext())
    deps.local_identity = patient()
    deps.service.grant(patient(), "caregiver", ["acknowledge_alerts"])
    deps.local_identity = caregiver()
    acknowledgement = mcp.tools["acknowledge_alert"](alert["id"], FakeContext())
    assert acknowledgement["speakable"] == "CareLoop update acknowledged."
    after = mcp.tools["list_generic_notifications"](FakeContext())
    assert after["speakable"] == "There are no new CareLoop updates."
    assert after["refs"][0]["status"] == "acknowledged"
    assert "pain" not in str(acknowledgement).lower()


def test_patient_cannot_list_caregiver_notifications() -> None:
    mcp, _deps = build([100], patient())
    with pytest.raises(ToolError, match="notifications are unavailable"):
        mcp.tools["list_generic_notifications"](FakeContext())


def test_delete_of_missing_record_is_an_error() -> None:
    mcp, _deps = build([100], patient())
    with pytest.raises(ToolError, match="No active CareLoop record was deleted"):
        mcp.tools["delete_care_record"]("missing", FakeContext())


def test_search_returns_match_refs_and_accepts_relative_dates() -> None:
    now = [1_791_936_000]
    mcp, _deps = build(now, patient())
    recorded = mcp.tools["record_pain_observation"](4, "search-1", FakeContext())
    found = mcp.tools["search_care_history"]("pain", FakeContext(), "last_7_days")
    assert found["speakable"] == "Found 1 matching record."
    assert found["refs"][0]["id"] == recorded["refs"][0]["id"]
    assert mcp.tools["search_care_history"]("nothing-here", FakeContext())["speakable"] == "No matching record found."


def test_sensitive_tool_details_are_never_in_model_results() -> None:
    """Regression eval: source excerpts, observations, and handoffs stay off voice."""
    now = [1_791_936_000]
    mcp, deps = build(now, patient())
    secret = "PRIVATE-CARE-DETAIL-719"
    source = deps.service.create_document(patient(), "Synthetic plan", [{"page": 1, "excerpt": secret}], reviewed=True)
    results = [
        mcp.tools["record_pain_observation"](9, "secret-observation", FakeContext()),
        mcp.tools["get_care_plan_source"](source["id"], FakeContext()),
        mcp.tools["create_visit_handoff"]("last_7_days", FakeContext()),
        mcp.tools["list_care_records"](FakeContext()),
    ]
    for result in results:
        assert secret not in str(result)
        assert "9" not in result["speakable"]

    view = mcp.tools["get_private_view"]("plan-source", FakeContext(), [source["id"]])
    assert view["data"]["sources"][0]["page_excerpts"][0]["excerpt"] == secret
    trend = mcp.tools["get_private_view"]("check-in-trend", FakeContext())
    assert trend["data"]["observations"][0]["pain_score"] == 9


def test_private_view_respects_caregiver_scope() -> None:
    mcp, deps = build([100], patient())
    mcp.tools["record_pain_observation"](6, "scope-1", FakeContext())
    deps.service.grant(patient(), "caregiver", ["read_tasks"])
    deps.local_identity = caregiver()
    assert mcp.tools["get_private_view"]("tasks", FakeContext())["data"] == {"items": []}
    for view in ("check-in-trend", "visit-handoff", "care-circle", "export"):
        with pytest.raises(ToolError, match="view is unavailable"):
            mcp.tools["get_private_view"](view, FakeContext())
    with pytest.raises(ToolError, match="view is unavailable"):
        mcp.tools["get_private_view"]("not-a-view", FakeContext())


def test_server_registers_static_data_free_mcp_app_resources(tmp_path) -> None:
    from care_loop.config import Settings

    from dataclasses import replace

    settings = replace(Settings.from_env(), db_path=str(tmp_path / "x.db"))
    mcp = build_server(build_deps(settings, local_identity=patient()))

    async def inspect():
        resources = {str(r.uri): r for r in await mcp.list_resources()}
        tools = {t.name: t for t in await mcp.list_tools()}
        html = (await mcp.read_resource("ui://careloop/plan-review"))[0].content
        return resources, tools, html

    resources, tools, html = asyncio.run(inspect())
    assert set(resources) == {f"ui://careloop/{view}" for view in VIEWS}
    assert all(r.mime_type == "text/html;profile=mcp-app" for r in resources.values())
    assert tools["approve_plan_item"].meta == {"ui": {"resourceUri": "ui://careloop/plan-review"}}
    assert tools["approve_plan_item"].output_schema["required"] == ["status", "speakable", "surface", "view", "refs"]
    assert "ui/initialize" in html and "get_private_view" in html and "__CARELOOP_VIEW__" not in html
    assert "innerHTML" not in html


def test_alexa_instructions_require_speakable_only() -> None:
    assert "speak only the speakable field" in INSTRUCTIONS
    assert "never quote, summarize, or expose" in INSTRUCTIONS


class ElicitingContext(FakeContext):
    def __init__(self, action: str, score: int | None = None) -> None:
        self.action, self.score, self.messages = action, score, []

    async def elicit(self, message, schema):
        self.messages.append(message)
        if self.action != "accept":
            return type("Declined", (), {"action": self.action})()
        return type("Accepted", (), {"action": "accept", "data": schema(pain_score=self.score)})()


def test_daily_checkin_asks_its_own_follow_up_question() -> None:
    mcp, deps = build([1_791_936_000], patient())
    ctx = ElicitingContext("accept", 6)
    result = asyncio.run(mcp.tools["start_daily_checkin"](ctx))
    assert ctx.messages == ["On a scale from 0 to 10, what's your pain score today?"]
    assert result["speakable"] == "Check-in recorded." and "pain_score" not in str(result)
    assert deps.service.list_observations(patient())[0]["pain_score"] == 6

    skipped = asyncio.run(mcp.tools["start_daily_checkin"](ElicitingContext("decline")))
    assert "Nothing was recorded" in skipped["speakable"]
    assert len(deps.service.list_observations(patient())) == 1


def test_daily_checkin_refuses_caregiver_without_write_scope_before_asking() -> None:
    mcp, deps = build([100], patient())
    deps.service.grant(patient(), "caregiver", ["read_tasks"])
    deps.local_identity = caregiver()
    ctx = ElicitingContext("accept", 5)
    with pytest.raises(ToolError, match="check-in couldn't be completed"):
        asyncio.run(mcp.tools["start_daily_checkin"](ctx))
    assert ctx.messages == []
