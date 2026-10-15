"""Alexa+ simulator host: SDK normalization, planning, confirmation, privacy, and a live E2E."""
from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.request import urlopen

import pytest
from fastapi.testclient import TestClient
from mcp.types import CallToolResult, TextContent, Tool, ToolAnnotations

from alexa_sim.app import create_alexa_sim_app
from alexa_sim.config import AlexaSimSettings
from alexa_sim.devices import Device, DeviceKind
from alexa_sim.mcp_pool import AccountSession, Question, is_app_only, normalize_result, normalize_tool
from alexa_sim.orchestrator import Orchestrator, parse_answer, strip_wake_word
from alexa_sim.planners import MockReplay, OllamaPlanner
from alexa_sim.reply_policy import DISCLAIMER, compose_reply, screen_payload

ROOT = Path(__file__).resolve().parents[2]


# ---- SDK normalization ---------------------------------------------------------------
def test_normalizes_real_sdk_tool_and_result_objects() -> None:
    tool = Tool(name="revoke_caregiver", description="Revoke", inputSchema={"type": "object", "properties": {"invitation_id": {"type": "string"}}},
                annotations=ToolAnnotations(destructiveHint=True), _meta={"ui": {"resourceUri": "ui://careloop/care-circle"}})
    normalized = normalize_tool(tool)
    assert normalized["inputSchema"]["properties"]["invitation_id"] == {"type": "string"}
    assert normalized["annotations"]["destructiveHint"] is True
    assert normalized["_meta"]["ui"]["resourceUri"] == "ui://careloop/care-circle"

    ok = normalize_result(CallToolResult(content=[TextContent(type="text", text="{}")], structuredContent={"speakable": "Done."}))
    assert ok["structuredContent"] == {"speakable": "Done."} and ok["isError"] is False
    error = normalize_result(CallToolResult(content=[TextContent(type="text", text="Error executing tool x: Nope.")], isError=True))
    assert error["isError"] is True and error["text"].endswith("Nope.")


def test_app_only_tools_are_hidden_from_the_model() -> None:
    session = AccountSession("maya", worker=None, tools=[
        {"name": "list_care_tasks", "_meta": {"ui": {"resourceUri": "ui://careloop/tasks"}}},
        {"name": "get_private_view", "_meta": {"ui": {"visibility": ["app"]}}},
    ])
    assert [t["name"] for t in session.model_tools] == ["list_care_tasks"]
    assert is_app_only(session.tools[1]) and not is_app_only(session.tools[0])


# ---- reply policy ------------------------------------------------------------------------
def ok(speakable: str, view: str = "ui://careloop/tasks", **extra) -> dict:
    return {"isError": False, "structuredContent": {"status": "ok", "speakable": speakable, "surface": "private_screen",
                                                    "view": view, "refs": [], **extra}}


def test_reply_speaks_actions_not_lookups_and_never_private_fields() -> None:
    results = [("list_care_tasks", ok("You have 2 drafts."), True),
               ("approve_plan_item", ok("Plan task approved and now active.", private={"pain_score": 9}), False),
               ("approve_plan_item", ok("Plan rule approved and now active."), False)]
    reply = compose_reply(results)
    assert reply.startswith("Plan task approved and now active. Plan rule approved and now active.")
    assert DISCLAIMER in reply and "drafts" not in reply and "9" not in reply


def test_errors_are_spoken_generically_and_never_rendered() -> None:
    error = {"isError": True, "structuredContent": None, "text": "Error executing tool delete_care_record: No active CareLoop record was deleted."}
    assert compose_reply([("delete_care_record", error, False)]) == "No active CareLoop record was deleted."
    assert screen_payload([("delete_care_record", error, False)], Device("show", DeviceKind.SHOW, "maya")) is None


def test_dot_never_gets_a_screen() -> None:
    assert screen_payload([("list_care_tasks", ok("x"), True)], Device("dot", DeviceKind.DOT, "sam")) is None


# ---- orchestrator ------------------------------------------------------------------------
class FakePool:
    def __init__(self, tools: list[dict], responses: dict) -> None:
        self.accounts = {"maya": AccountSession("maya", worker=None, tools=tools)}
        self.responses, self.calls = responses, []

    def linked(self, account):
        return account in self.accounts

    async def call_tool(self, account, name, arguments, source="model"):
        self.calls.append((name, arguments))
        response = self.responses[name]
        return response(arguments) if callable(response) else response


TOOLS = [
    {"name": "list_care_tasks", "annotations": {"readOnlyHint": True}, "_meta": {"ui": {"resourceUri": "ui://careloop/tasks"}}},
    {"name": "approve_plan_item", "annotations": {"readOnlyHint": False}, "_meta": {"ui": {"resourceUri": "ui://careloop/plan-review"}}},
    {"name": "list_care_circle", "annotations": {"readOnlyHint": True}, "_meta": {"ui": {"resourceUri": "ui://careloop/care-circle"}}},
    {"name": "revoke_caregiver", "annotations": {"destructiveHint": True}, "_meta": {"ui": {"resourceUri": "ui://careloop/care-circle"}}},
    {"name": "get_private_view", "annotations": {"readOnlyHint": True}, "_meta": {"ui": {"visibility": ["app"]}}},
]


@pytest.mark.asyncio
async def test_approve_uses_discovered_refs_and_renders_tool_declared_view() -> None:
    pool = FakePool(TOOLS, {
        "list_care_tasks": ok("1 draft needs review.", refs=[{"id": "d1", "kind": "task", "status": "draft", "label": "draft task 1"},
                                                             {"id": "a1", "kind": "task", "status": "active", "label": "active task 1"}]),
        "approve_plan_item": lambda args: ok("Plan task approved and now active.", view="ui://careloop/plan-review"),
    })
    device = Device("show", DeviceKind.SHOW, "maya", account="maya")
    turn = await Orchestrator(pool).respond(device, "Alexa, approve my plan")
    assert pool.calls == [("list_care_tasks", {}), ("approve_plan_item", {"record_id": "d1"})]
    assert turn.reply.startswith("Plan task approved")
    assert turn.screen["resource_uri"] == "ui://careloop/plan-review"
    assert [m["role"] for m in device.history] == ["user", "assistant", "tool", "assistant", "tool", "assistant"]
    assert device.history[1]["tool_calls"][0]["function"]["name"] == "list_care_tasks"


@pytest.mark.asyncio
async def test_destructive_tool_waits_for_confirmation() -> None:
    pool = FakePool(TOOLS, {
        "list_care_circle": ok("1 caregiver.", view="ui://careloop/care-circle",
                               refs=[{"id": "g1", "kind": "caregiver_grant", "status": "active", "label": "caregiver access 1"}]),
        "revoke_caregiver": ok("Caregiver access revoked.", view="ui://careloop/care-circle"),
    })
    device = Device("show", DeviceKind.SHOW, "maya", account="maya")
    orchestrator = Orchestrator(pool)

    first = await orchestrator.respond(device, "remove Sam")
    assert first.needs_confirmation and "Say confirm" in first.reply
    assert ("revoke_caregiver", {"invitation_id": "g1"}) not in pool.calls

    cancelled = await orchestrator.respond(device, "cancel")
    assert "didn't change" in cancelled.reply and device.pending is None

    await orchestrator.respond(device, "remove Sam")
    confirmed = await orchestrator.respond(device, "confirm")
    assert pool.calls[-1] == ("revoke_caregiver", {"invitation_id": "g1"})
    assert confirmed.reply.startswith("Caregiver access revoked.")


@pytest.mark.asyncio
async def test_medical_advice_is_refused_without_any_tool_call() -> None:
    pool = FakePool(TOOLS, {})
    turn = await Orchestrator(pool).respond(Device("show", DeviceKind.SHOW, "maya", account="maya"), "Alexa, should I double my medication?")
    assert pool.calls == [] and "can't give medical advice" in turn.reply


@pytest.mark.asyncio
async def test_unlinked_device_and_wake_word() -> None:
    assert strip_wake_word("Hey Alexa, show my tasks") == "show my tasks"
    turn = await Orchestrator(FakePool(TOOLS, {})).respond(Device("dot", DeviceKind.DOT, "sam"), "Alexa, any updates?")
    assert "enable CareLoop" in turn.reply


@pytest.mark.asyncio
async def test_planner_failure_falls_back_to_mock_replay() -> None:
    class Broken:
        name = "ollama"
        async def next(self, *args):
            raise OSError("model offline")
    pool = FakePool(TOOLS, {"list_care_tasks": ok("You have 1 active task and 0 active follow-up rules.")})
    turn = await Orchestrator(pool, Broken()).respond(Device("show", DeviceKind.SHOW, "maya", account="maya"), "show my tasks")
    assert turn.planner == "mock" and turn.reply.startswith("You have 1 active task")


@pytest.mark.asyncio
async def test_ollama_planner_sees_schemas_and_only_voice_safe_results() -> None:
    sent = []
    def post(url, body):
        sent.append(json.loads(body))
        return json.dumps({"message": {"tool_calls": [{"function": {"name": "approve_plan_item", "arguments": {"record_id": "d1"}}}]}}).encode()
    planner = OllamaPlanner("http://ollama", "local", post=post)
    tools = [{"name": "approve_plan_item", "description": "Approve", "inputSchema": {"type": "object", "properties": {"record_id": {"type": "string"}}}}]
    prior = ok("1 draft.", refs=[{"id": "d1", "label": "draft task 1"}], secret="PRIVATE")
    action = await planner.next("approve it", tools, [], [("list_care_tasks", {}, prior)])
    assert (action.tool, action.arguments) == ("approve_plan_item", {"record_id": "d1"})
    payload = sent[0]
    assert payload["tools"][0]["function"]["parameters"]["properties"]["record_id"] == {"type": "string"}
    assert "PRIVATE" not in json.dumps(payload["messages"])


# ---- follow-up questions (MCP elicitation) ---------------------------------------------
PAIN_SCHEMA = {"type": "object", "required": ["pain_score"],
               "properties": {"pain_score": {"type": "integer", "minimum": 0, "maximum": 10}}}


@pytest.mark.parametrize(("text", "expected"), [("seven", 7), ("it's about 4", 4), ("0", 0), ("ten", 10)])
def test_parse_answer_fills_integer_fields(text, expected) -> None:
    assert parse_answer(text, PAIN_SCHEMA) == ({"pain_score": expected}, None)


@pytest.mark.parametrize("text", ["twelve", "11", "banana", "6.5"])
def test_parse_answer_reprompts_out_of_range_or_missing(text) -> None:
    content, reprompt = parse_answer(text, PAIN_SCHEMA)
    assert content is None and "0 to 10" in reprompt


class ElicitingPool(FakePool):
    """Simulates a server tool that pauses on an elicitation before returning."""
    def __init__(self) -> None:
        super().__init__([{"name": "start_daily_checkin", "annotations": {"readOnlyHint": False},
                           "_meta": {"ui": {"resourceUri": "ui://careloop/check-in-trend"}}}], {})
        self.questions = {"maya": asyncio.Queue()}
        self.answers = []

    async def call_tool(self, account, name, arguments, source="model"):
        self.calls.append((name, arguments))
        while True:
            question = Question(account, "On a scale from 0 to 10, what's your pain score today?", PAIN_SCHEMA,
                                asyncio.get_running_loop().create_future())
            await self.questions[account].put(question)
            answer = await question.answer
            self.answers.append(answer)
            if answer["action"] != "accept":
                return ok("Okay, I skipped today's check-in. Nothing was recorded.", view="ui://careloop/check-in-trend")
            return ok("Check-in recorded.", view="ui://careloop/check-in-trend")


@pytest.mark.asyncio
async def test_elicitation_pauses_the_tool_and_the_next_utterance_answers_it() -> None:
    pool = ElicitingPool()
    device = Device("show", DeviceKind.SHOW, "maya", account="maya")
    orchestrator = Orchestrator(pool)

    asked = await orchestrator.respond(device, "Alexa, do my check-in")
    assert asked.reply.startswith("On a scale from 0 to 10") and asked.expects_reply
    assert device.awaiting is not None and device.history == []

    reprompt = await orchestrator.respond(device, "twelve")
    assert reprompt.reply == "Sorry, please say a whole number from 0 to 10." and reprompt.expects_reply

    done = await orchestrator.respond(device, "seven")
    assert done.reply.startswith("Check-in recorded.") and not done.expects_reply
    assert pool.answers == [{"action": "accept", "content": {"pain_score": 7}}]
    assert device.awaiting is None and device.history[0] == {"role": "user", "content": "do my check-in"}
    assert done.screen["resource_uri"] == "ui://careloop/check-in-trend"


@pytest.mark.asyncio
async def test_elicitation_can_be_cancelled_by_voice() -> None:
    pool = ElicitingPool()
    device = Device("show", DeviceKind.SHOW, "maya", account="maya")
    orchestrator = Orchestrator(pool)
    await orchestrator.respond(device, "do my check-in")
    skipped = await orchestrator.respond(device, "cancel")
    assert pool.answers == [{"action": "decline"}] and "Nothing was recorded" in skipped.reply


# ---- live end-to-end against a real CareLoop MCP server ---------------------------------------
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def careloop_server(tmp_path):
    port = _free_port()
    env = {**os.environ, "CARELOOP_DB_PATH": str(tmp_path / "e2e.db"), "CARELOOP_PORT": str(port),
           "CARELOOP_API_TOKEN": "careloop-local-demo-token", "CARELOOP_DEMO_PATIENT": "demo-patient",
           "PYTHONPATH": str(ROOT / "server")}
    env.pop("CARELOOP_CAREGIVER_TOKEN", None)
    process = subprocess.Popen([sys.executable, "-m", "care_loop"], cwd=ROOT, env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                urlopen(f"http://127.0.0.1:{port}/healthz", timeout=0.5)
                break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("CareLoop server did not start")
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_full_demo_story_against_live_careloop(careloop_server) -> None:
    settings = AlexaSimSettings(mcp_url=careloop_server, planner="mock")
    with TestClient(create_alexa_sim_app(settings, planner=MockReplay())) as client:
        def say(device, text):
            out = client.post("/api/utterance", json={"device_id": device, "text": text}).json()
            return out

        assert client.post("/api/link", json={"account": "maya"}).status_code == 200
        linked = client.post("/api/link", json={"account": "sam"}).json()
        assert "get_private_view" not in linked["tools"]

        imported = say("show", "Alexa, I got a new care plan from my clinic")
        assert imported["reply"].startswith("Imported 3 plan items")
        assert imported["screen"]["resource_uri"] == "ui://careloop/plan-review"
        html = client.get("/api/apps/resource", params={"device_id": "show", "uri": "ui://careloop/plan-review"}).json()["html"]
        assert "ui/initialize" in html

        approved = say("show", "Alexa, approve my plan")
        assert approved["tools"] == ["list_care_tasks", "approve_plan_item", "approve_plan_item", "approve_plan_item"]
        assert say("show", "show my tasks")["reply"].startswith("You have 2 active tasks and 1 active follow-up rule.")

        # MCP App bridge: private detail only through the app-only tool, only for the Show.
        view = client.post("/api/apps/call", json={"device_id": "show", "name": "get_private_view", "arguments": {"view": "tasks"}}).json()
        assert "Take a short walk" in view["content"][0]["text"]
        assert client.post("/api/apps/call", json={"device_id": "dot", "name": "get_private_view", "arguments": {"view": "tasks"}}).status_code == 403

        invited = say("show", "Alexa, let my brother Sam see my tasks and get updates for two weeks")
        assert invited["reply"].startswith("Invitation created with 3 permissions")
        accepted = client.post("/api/invite/open").json()
        assert accepted["accepted"] is True

        assert say("dot", "Alexa, any CareLoop updates?")["reply"] == "There are no new CareLoop updates."
        say("show", "my pain is 8 yesterday")
        # The follow-up question is a real MCP elicitation from the server's tool.
        asked = say("show", "Alexa, do my check-in")
        assert asked["expects_reply"] and asked["reply"].startswith("On a scale from 0 to 10")
        assert say("show", "nine")["reply"].startswith("Check-in recorded.")
        kinds = [e.get("method") for e in client.get("/api/state").json()["trace"]]
        assert "elicitation/create" in kinds
        state = client.get("/api/state").json()
        assert next(d for d in state["devices"] if d["id"] == "dot")["notification"] is True

        update = say("dot", "Alexa, any CareLoop updates?")["reply"]
        assert update == "You have 1 new CareLoop update."
        denied = say("dot", "Alexa, what was Maya's pain score?")["reply"]
        assert "8" not in denied and "9" not in denied and "unavailable" in denied.lower()
        assert say("dot", "Alexa, mark it seen")["reply"] == "CareLoop update acknowledged."
        assert next(d for d in client.get("/api/state").json()["devices"] if d["id"] == "dot")["notification"] is False

        handoff = say("show", "Alexa, get me ready for my appointment")
        assert handoff["screen"]["resource_uri"] == "ui://careloop/visit-handoff"

        assert say("show", "Alexa, remove Sam")["needs_confirmation"] is True
        assert say("show", "confirm")["reply"].startswith("Caregiver access revoked.")
        assert "unavailable" in say("dot", "Alexa, any CareLoop updates?")["reply"].lower()

        # Every turn's spoken output on the Dot stayed within the voice-safe contract.
        dot_turns = [e for e in client.get("/api/state").json()["trace"] if e.get("type") == "turn" and e["device_id"] == "dot"]
        assert dot_turns and all("pain" not in t["reply"].lower() for t in dot_turns)

        assert client.post("/api/unlink/maya").json() == {"unlinked": True}
        assert client.post("/api/unlink/sam").json() == {"unlinked": True}


def test_simulator_page_has_required_label() -> None:
    class Pool:
        accounts = {}
        def linked(self, account): return False
        async def close(self): pass
    with TestClient(create_alexa_sim_app(AlexaSimSettings(), pool=Pool(), planner=MockReplay())) as client:
        out = client.get("/api/state").json()
        page = client.get("/").text
    assert "Not an Amazon product" in out["label"] and "/static/sim.js" in page


class FakeVoice:
    def __init__(self, tts=None, stt=None):
        self.tts, self.stt = tts, stt
    def warm_in_background(self): pass
    def describe(self): return {"tts": "kokoro" if self.tts else "browser", "stt": "whisper" if self.stt else "browser"}


def test_voice_endpoints_use_local_engines_or_defer_to_the_browser() -> None:
    class Pool:
        accounts = {}
        def linked(self, account): return False
        async def close(self): pass
    tts = SimpleNamespace(synthesize=lambda text: b"RIFF-fake-" + text.encode())
    stt = SimpleNamespace(transcribe=lambda pcm, rate: "alexa do my check-in" if pcm else "")
    with TestClient(create_alexa_sim_app(AlexaSimSettings(), pool=Pool(), planner=MockReplay(), voice=FakeVoice(tts, stt))) as client:
        assert client.get("/api/voice").json() == {"tts": "kokoro", "stt": "whisper"}
        audio = client.post("/api/tts", json={"text": "Check-in recorded."})
        assert audio.headers["content-type"] == "audio/wav" and audio.content.endswith(b"Check-in recorded.")
        assert client.post("/api/stt", content=b"\x00\x01" * 100).json() == {"text": "alexa do my check-in"}
        assert client.post("/api/stt", content=b"\x00" * (30 * 16_000 * 2 + 2)).status_code == 413
    with TestClient(create_alexa_sim_app(AlexaSimSettings(), pool=Pool(), planner=MockReplay(), voice=FakeVoice())) as client:
        assert client.post("/api/tts", json={"text": "x"}).status_code == 404
        assert client.post("/api/stt", content=b"\x00").status_code == 404
