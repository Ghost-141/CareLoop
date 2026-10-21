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
from alexa_sim.planners import MockReplay, OllamaPlanner, OpenAIPlanner, chat_completions_url
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
@pytest.mark.parametrize("phrase, when", [("Alexa, what medicine do I take before breakfast?", "breakfast"),
                                          ("Alexa, what medicine do I have to take before dinner?", "dinner"),
                                          ("which medications do I take?", None)])
async def test_asking_which_medicines_reads_the_plan_instead_of_refusing(phrase, when) -> None:
    pool = FakePool(TOOLS, {"list_care_tasks": ok("In the morning: Omeprazole at 7:30 AM, before breakfast, from line 6.")})
    turn = await Orchestrator(pool).respond(Device("show", DeviceKind.SHOW, "maya", account="maya"), phrase)
    expected = {"medicines": True} | ({"when": when} if when else {})
    assert pool.calls == [("list_care_tasks", expected)] and "can't give medical advice" not in turn.reply


@pytest.mark.asyncio
@pytest.mark.parametrize("phrase", ["Alexa, what medicine should I take for my headache?",
                                    "Alexa, which medicine can I skip today?", "Alexa, what dose of my medicine is safe?"])
async def test_medicine_questions_asking_for_advice_are_still_refused(phrase) -> None:
    pool = FakePool(TOOLS, {})
    turn = await Orchestrator(pool).respond(Device("show", DeviceKind.SHOW, "maya", account="maya"), phrase)
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


@pytest.mark.parametrize(("given", "expected"), [
    ("https://gw.example/v1/chat/completions", "https://gw.example/v1/chat/completions"),
    ("https://gw.example/v1", "https://gw.example/v1/chat/completions"),
    ("https://gw.example/v1/", "https://gw.example/v1/chat/completions"),
    ("http://localhost:1234", "http://localhost:1234/v1/chat/completions")])
def test_openai_endpoint_url_accepts_base_or_full_url(given, expected) -> None:
    assert chat_completions_url(given) == expected


@pytest.mark.asyncio
async def test_openai_planner_uses_the_openai_format_and_only_voice_safe_results() -> None:
    sent = []
    def post(url, body):
        sent.append((url, json.loads(body)))
        return json.dumps({"choices": [{"message": {"content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "approve_plan_item", "arguments": "{\"record_id\": \"d1\"}"}}]}}]}).encode()
    planner = OpenAIPlanner("https://gw.example/v1", "any-model", "sk-test", post=post)
    tools = [{"name": "approve_plan_item", "description": "Approve", "inputSchema": {"type": "object", "properties": {"record_id": {"type": "string"}}}}]
    prior = ok("1 draft.", refs=[{"id": "d1", "label": "draft task 1"}], secret="PRIVATE")
    action = await planner.next("approve it", tools, [], [("list_care_tasks", {}, prior)])
    assert (action.tool, action.arguments) == ("approve_plan_item", {"record_id": "d1"})
    url, payload = sent[0]
    assert url == "https://gw.example/v1/chat/completions" and payload["model"] == "any-model"
    assistant, tool_message = payload["messages"][-2:]
    assert assistant["tool_calls"][0]["function"]["arguments"] == "{}"  # arguments travel as a JSON string
    assert tool_message["tool_call_id"] == assistant["tool_calls"][0]["id"]
    assert "PRIVATE" not in json.dumps(payload["messages"])


@pytest.mark.asyncio
async def test_openai_planner_translates_earlier_turns_stored_in_the_ollama_shape() -> None:
    sent = []
    planner = OpenAIPlanner("https://gw.example/v1", "m", post=lambda url, body: (sent.append(json.loads(body)),
                            json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode())[1])
    history = [{"role": "user", "content": "my pain is 4"},
               {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "record_pain_observation", "arguments": {"pain_score": 4}}}]},
               {"role": "tool", "tool_name": "record_pain_observation", "content": "{\"speakable\": \"Check-in recorded.\"}"},
               {"role": "assistant", "content": "Check-in recorded."}]
    await planner.next("thanks", [], history, [], context={"task": {"id": "t1", "title": "Walk", "times": ["08:00"]}})
    messages = sent[0]["messages"]
    assert [m["role"] for m in messages].count("system") == 1 and messages[0]["role"] == "system"
    assert "id=t1" in messages[0]["content"]  # the "it / that one" note travels inside the first system message
    call = next(m for m in messages if m.get("tool_calls"))["tool_calls"][0]
    result = next(m for m in messages if m["role"] == "tool")
    assert call["type"] == "function" and call["function"]["arguments"] == "{\"pain_score\": 4}"
    assert result["tool_call_id"] == call["id"] and "tool_name" not in result


@pytest.mark.asyncio
async def test_openai_planner_returns_plain_text_when_no_tool_is_called() -> None:
    planner = OpenAIPlanner("https://gw.example/v1", "m", post=lambda url, body: json.dumps(
        {"choices": [{"message": {"content": [{"type": "text", "text": "I can't advise on that."}]}}]}).encode())
    action = await planner.next("should I double my dose", [], [], [])
    assert (action.tool, action.say) == (None, "I can't advise on that.")


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
        if name != "start_daily_checkin":
            response = self.responses[name]
            return response(arguments) if callable(response) else response
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
def careloop_server_with_consent(tmp_path, monkeypatch):
    monkeypatch.setenv("CARELOOP_TEST_REQUIRE_CONSENT", "true")
    yield from _careloop_server(tmp_path)


@pytest.fixture
def careloop_server(tmp_path):
    yield from _careloop_server(tmp_path)


def _careloop_server(tmp_path, db_name: str = "e2e.db", extra_env: dict | None = None):
    port = _free_port()
    env = {**os.environ, "CARELOOP_DB_PATH": str(tmp_path / db_name), "CARELOOP_PORT": str(port),
           "CARELOOP_API_TOKEN": "careloop-local-demo-token", "CARELOOP_DEMO_PATIENT": "demo-patient",
           "PYTHONPATH": str(ROOT / "server")}
    env.pop("CARELOOP_CAREGIVER_TOKEN", None)
    # Deterministic intake for tests: pattern fallback, no OCR or model downloads.
    env |= {"CARELOOP_INTAKE_LLM": "none", "CARELOOP_INTAKE_OCR": "none",
            # Feature tests start past the one-time data-use consent; it has its own live test below.
            "CARELOOP_REQUIRE_CONSENT": os.environ.get("CARELOOP_TEST_REQUIRE_CONSENT", "false"),
            "CARELOOP_DEMO_RESET": "true"} | (extra_env or {})
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


@pytest.fixture
def careloop_server_with_a_visit_coming_up(tmp_path):
    """A real server on a database that already holds: a visit tomorrow, one saved question, a check-in yesterday."""
    import time
    from datetime import date, timedelta
    from care_loop.auth import Identity
    from care_loop.core import CareLoopService
    from care_loop.storage import CareLoopStorage

    storage = CareLoopStorage(str(tmp_path / "suggest.db"))
    service = CareLoopService(storage, storage.clock, 365)
    maya = Identity("demo-patient", "patient", "demo-patient")
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    service.write(maya, "PLAN_NOTE", {"item_kind": "appointment", "label": "Follow-up visit", "status": "active",
                                      "text": f"Follow-up appointment on {tomorrow}.", "due_date": tomorrow}, reviewed=True)
    service.add_clinician_question(maya, "can I stop my medicine early")
    service.record_observation(maya, pain_score=4, observed_at=int(time.time()) - 86_400, idempotency_key="seed-yesterday")
    storage.close()
    # hour 0 so "you haven't checked in today" applies whatever the time of day the test runs
    yield from _careloop_server(tmp_path, db_name="suggest.db", extra_env={"CARELOOP_SUGGEST_CHECKIN_HOUR": "0"})


def test_suggestions_end_to_end_against_live_careloop(careloop_server_with_a_visit_coming_up) -> None:
    settings = AlexaSimSettings(mcp_url=careloop_server_with_a_visit_coming_up, planner="mock")
    with TestClient(create_alexa_sim_app(settings, planner=MockReplay())) as client:
        client.post("/api/link", json={"account": "maya"})
        client.post("/api/link", json={"account": "sam"})
        say = lambda device, text: client.post("/api/utterance", json={"device_id": device, "text": text}).json()

        # 1. Maya asks: both things that apply are raised, the offer is last, no private text is spoken.
        asked = say("show", "Alexa, anything I should know?")
        assert asked["tools"] == ["get_suggestions"] and asked["expects_reply"] is True
        reply = asked["reply"]
        assert reply.startswith("You have 2 things worth a look. You haven't checked in today. Your visit is tomorrow. "
                                "You have 1 question saved for your clinician.")
        assert reply.endswith("Want me to prepare the handoff?")
        assert "medicine" not in reply.lower() and "4" not in reply  # neither the saved question nor a score

        # 2. "yes" runs exactly the step that was offered.
        handoff = say("show", "yes")
        assert handoff["tools"] == ["create_visit_handoff"]
        assert handoff["reply"].startswith("Your visit handoff is ready on your private screen. It includes 1 question for your clinician.")
        assert handoff["screen"]["resource_uri"] == "ui://careloop/visit-handoff"

        # 3. A family member gets nothing: suggestions are for the patient.
        sam = say("dot", "Alexa, anything I should know?")["reply"]
        assert sam == "Suggestions are unavailable." and "visit" not in sam.lower()

        # 4. The patient can turn them off and back on by voice.
        assert "suggestions are off" in say("show", "Alexa, turn suggestions off")["reply"]
        assert say("show", "Alexa, anything I should know?")["reply"].startswith("Suggestions are turned off.")
        assert "suggestions are on" in say("show", "Alexa, turn suggestions on")["reply"]
        assert "Your visit is tomorrow" in say("show", "Alexa, anything I should know?")["reply"]

        # 5. Checking in clears that suggestion, and the visit alone remains.
        say("show", "Alexa, my pain is 5 today")
        again = say("show", "Alexa, anything I should know?")["reply"]
        assert again.startswith("Your visit is tomorrow.") and "checked in" not in again


@pytest.fixture
def careloop_server_with_approved_medicines(tmp_path):
    """A real server whose database holds an approved, cited plan: two medicines and a fever warning."""
    from care_loop.auth import Identity
    from care_loop.core import CareLoopService
    from care_loop.storage import CareLoopStorage

    storage = CareLoopStorage(str(tmp_path / "teach.db"))
    service = CareLoopService(storage, storage.clock, 365)
    maya = Identity("demo-patient", "patient", "demo-patient")
    service.accept_data_use(maya)
    lines = {"p1:L3": "Amoxicillin 500 mg by mouth every 8 hours for 7 days.",
             "p1:L5": "Ibuprofen 400 mg every 6 hours as needed for pain.",
             "p1:L8": "Seek emergency care if you have a fever above 39 C."}
    doc = service.create_document(maya, "Discharge plan", [{"page": 1, "excerpt": t, "line_id": i} for i, t in lines.items()],
                                  reviewed=True)

    def item(record_type, line, **fields):
        source = [{"id": line, "page": 1, "text": lines[line], "method": "text", "confidence_pct": 100}]
        service.write(maya, record_type, {"status": "active", "text": lines[line], "source": source, "page": 1} | fields,
                      source_id=doc["id"], reviewed=True)

    item("PLAN_TASK", "p1:L3", item_kind="medication_task", label="Antibiotic", medication={"name": "Amoxicillin"},
         frequency="three_times_daily", times=["08:00", "14:00", "20:00"])
    item("PLAN_TASK", "p1:L5", item_kind="medication_task", label="Pain relief", medication={"name": "Ibuprofen"},
         frequency="as_needed", times=[])
    item("PLAN_NOTE", "p1:L8", item_kind="warning_sign", label="Fever warning")
    storage.close()
    yield from _careloop_server(tmp_path, db_name="teach.db")


def test_teach_back_end_to_end_against_live_careloop(careloop_server_with_approved_medicines) -> None:
    settings = AlexaSimSettings(mcp_url=careloop_server_with_approved_medicines, planner="mock")
    with TestClient(create_alexa_sim_app(settings, planner=MockReplay())) as client:
        client.post("/api/link", json={"account": "maya"})
        client.post("/api/link", json={"account": "sam"})
        say = lambda device, text: client.post("/api/utterance", json={"device_id": device, "text": text}).json()

        # 1. The server asks its own questions; a wrong answer gets one more try, then the next question.
        first = say("show", "Alexa, check I understood my plan")
        assert first["tools"] == ["start_teach_back"] and first["expects_reply"] is True
        assert first["reply"] == "Let's check 3 things. How often do you take Amoxicillin?"
        assert say("show", "twice a day")["reply"] == "Not quite. Try again: How often do you take Amoxicillin?"
        assert say("show", "every 8 hours")["reply"] == ("That's right. Do you take Ibuprofen at set times, "
                                                          "or only when you need it?")

        # 2. A new "Alexa, …" request is not taken as an answer: the place is saved and the request is handled.
        interrupted = say("show", "Alexa, anything I should know?")
        assert interrupted["reply"].startswith("Okay, I've saved your place. 2 questions left.")
        assert "get_suggestions" in interrupted["tools"]

        # 3. "Check my understanding" picks up where it stopped; "I don't know" reads the plan back and moves on.
        resumed = say("show", "Alexa, check my understanding")
        assert resumed["reply"] == ("Let's pick up where we left off. Do you take Ibuprofen at set times, "
                                    "or only when you need it?")
        unsure = say("show", "I don't know")["reply"]
        assert unsure == ("That's okay. Your plan says: Ibuprofen 400 mg every 6 hours as needed for pain. "
                          "Next: At what temperature does your plan say to get help?")
        done = say("show", "39 degrees")
        assert done["reply"] == ("That's right. Done. You got 2 of 3 right. The one to look at again is on your screen, "
                                 "with the line it came from.")
        assert done["screen"]["resource_uri"] == "ui://careloop/teach-back"

        # 4. The miss now shows up as a suggestion, and a family member can't start a teach-back.
        assert "Part of your plan needs another look." in say("show", "Alexa, anything I should know?")["reply"]
        sam = say("dot", "Alexa, check I understood my plan")["reply"]
        assert "Amoxicillin" not in sam and "Ibuprofen" not in sam


@pytest.mark.asyncio
@pytest.mark.parametrize("phrase", ["Alexa, check I understood my plan", "quiz me on my plan", "let's do a teach-back",
                                    "check my understanding", "check that I understand my medicines"])
async def test_scripted_planner_routes_teach_back_phrases(phrase) -> None:
    tools = [{"name": n, "annotations": {}} for n in ("start_teach_back", "start_daily_checkin", "list_care_tasks")]
    assert (await MockReplay().next(phrase, tools, [], [], {})).tool == "start_teach_back"


@pytest.mark.asyncio
@pytest.mark.parametrize("phrase, tool", [("Alexa, do my check-in", "start_daily_checkin"), ("what's on my plan", "list_care_tasks")])
async def test_check_in_and_the_task_list_are_not_teach_back(phrase, tool) -> None:
    tools = [{"name": n, "annotations": {}} for n in ("start_teach_back", "start_daily_checkin", "list_care_tasks")]
    assert (await MockReplay().next(phrase, tools, [], [], {})).tool == tool


@pytest.mark.asyncio
@pytest.mark.parametrize("phrase, tool", [
    ("Alexa, anything I should know?", "get_suggestions"), ("anything coming up", "get_suggestions"),
    ("what's next", "get_suggestions"), ("what needs my attention", "get_suggestions"),
    ("Alexa, turn suggestions off", "set_my_details"), ("turn my suggestions on", "set_my_details"),
    ("what do I need to do today", "list_my_assigned_tasks"),  # the task list is not a suggestion
])
async def test_scripted_planner_routes_suggestion_phrases(phrase, tool) -> None:
    tools = [{"name": n, "annotations": {}} for n in ("get_suggestions", "set_my_details", "list_my_assigned_tasks")]
    action = await MockReplay().next(phrase, tools, [], [], {})
    assert action.tool == tool


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

        asked = say("show", "Alexa, let my brother Sam see my tasks and get updates for two weeks")
        assert asked["reply"] == ("Sam will be able to see your tasks, get update alerts and mark updates as seen. "
                                  "Is that right?") and asked["expects_reply"]
        invited = say("show", "yes")
        assert invited["reply"].startswith("Invitation created: Sam can see your tasks, get update alerts and mark updates as seen.")
        accepted = client.post("/api/invite/open").json()
        assert accepted["accepted"] is True

        assert say("dot", "Alexa, any CareLoop updates?")["reply"] == "There are no new CareLoop updates."
        say("show", "my pain is 8 yesterday")
        # The follow-up question is a real MCP elicitation from the server's tool.
        asked = say("show", "Alexa, do my check-in")
        assert asked["expects_reply"] and asked["reply"].startswith("On a scale from 0 to 10")
        # The check-in continues with the patient's own plan tasks for today (chained elicitation).
        assert say("show", "nine")["reply"] == "Did you do Take a short walk today?"
        assert say("show", "yes")["reply"] == "Did you do Complete the evening check-in today?"
        done = say("show", "not yet")
        assert done["reply"].startswith("Check-in recorded. You did 1 of 2 tasks. Complete the evening check-in is still to do.")
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
        assert say("dot", "Alexa, any CareLoop updates?")["reply"].startswith("You don't have access to the patient's CareLoop")

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


def test_family_member_shares_a_document_and_patient_is_told(careloop_server) -> None:
    settings = AlexaSimSettings(mcp_url=careloop_server, planner="mock")
    with TestClient(create_alexa_sim_app(settings, planner=MockReplay())) as client:
        client.post("/api/link", json={"account": "maya"})
        client.post("/api/link", json={"account": "sam"})
        say = lambda device, text: client.post("/api/utterance", json={"device_id": device, "text": text}).json()

        refused = client.post("/api/documents/share", params={"account": "sam", "sample": "typed"})
        assert refused.status_code == 403  # no upload permission yet

        say("show", "Alexa, let my brother Sam see my tasks and upload documents")
        invited = say("show", "yes")
        assert invited["reply"].startswith("Invitation created: Sam can see your tasks and share documents with you.")
        assert client.post("/api/invite/open").json()["accepted"] is True

        shared = client.post("/api/documents/share", params={"account": "sam", "sample": "typed", "doc_type": "prescription"})
        assert shared.status_code == 200
        for _ in range(60):
            turns = [e for e in client.get("/api/state").json()["trace"] if e.get("type") == "turn" and e["planner"] == "host"]
            if any(t["device_id"] == "show" for t in turns):
                break
            time.sleep(0.25)
        assert any(t["device_id"] == "dot" and "sent it to Maya" in t["reply"] for t in turns)
        ready = next(t for t in turns if t["device_id"] == "show")
        assert ready["reply"].startswith("Your document is ready.")
        assert "Medicine items are approved on your screen." in ready["reply"]

        status = say("show", "Alexa, is my document ready?")
        assert status["screen"]["resource_uri"] == "ui://careloop/plan-review"
        assert "Amoxicillin" not in status["reply"]


def _wait_for(client, predicate, tries=120):
    for _ in range(tries):
        turns = [e for e in client.get("/api/state").json()["trace"] if e.get("type") == "turn" and e["planner"] == "host"]
        if predicate(turns):
            return turns
        time.sleep(0.25)
    pytest.fail("the expected announcement never came")


def test_sharing_gets_an_immediate_answer_then_the_ready_message_which_can_be_fetched_again(careloop_server) -> None:
    settings = AlexaSimSettings(mcp_url=careloop_server, planner="mock")
    with TestClient(create_alexa_sim_app(settings, planner=MockReplay())) as client:
        client.post("/api/link", json={"account": "maya"})
        assert client.get("/api/state").json()["announce_seq"] == 0
        client.post("/api/documents/share", params={"account": "maya", "sample": "typed", "doc_type": "prescription"})
        turns = _wait_for(client, lambda t: sum(1 for x in t if x["device_id"] == "show") >= 2)
        shows = [t["reply"] for t in turns if t["device_id"] == "show"]
        assert shows[0].startswith("Got it. I'm reading your document now.")
        assert shows[1].startswith("Your document is ready.")
        # A page that missed the push can ask for anything newer than what it has seen.
        everything = client.get("/api/announcements", params={"after": 0}).json()
        assert [i["reply"][:8] for i in everything["items"]] == ["Got it. ", "Your doc"]
        assert everything["items"][1]["screen"]["resource_uri"] == "ui://careloop/plan-review"
        later = client.get("/api/announcements", params={"after": everything["items"][0]["id"]}).json()
        assert [i["id"] for i in later["items"]] == [everything["items"][1]["id"]]
        assert client.get("/api/state").json()["announce_seq"] == everything["latest"]


def test_ready_message_waits_for_maya_to_enable_her_show(careloop_server) -> None:
    settings = AlexaSimSettings(mcp_url=careloop_server, planner="mock")
    with TestClient(create_alexa_sim_app(settings, planner=MockReplay())) as client:
        client.post("/api/link", json={"account": "maya"})
        client.post("/api/link", json={"account": "sam"})
        say = lambda device, text: client.post("/api/utterance", json={"device_id": device, "text": text}).json()
        say("show", "Alexa, let my brother Sam see my tasks and upload documents")
        say("show", "yes")
        client.post("/api/invite/open")
        client.post("/api/unlink/maya")  # Maya's Show isn't enabled when Sam's document finishes
        client.post("/api/documents/share", params={"account": "sam", "sample": "typed"})
        time.sleep(8)
        assert client.get("/api/announcements").json()["items"] == [] or all(
            i["device_id"] == "dot" for i in client.get("/api/announcements").json()["items"])
        client.post("/api/link", json={"account": "maya"})
        turns = _wait_for(client, lambda t: any(x["device_id"] == "show" for x in t))
        assert next(t for t in turns if t["device_id"] == "show")["reply"].startswith("Your document is ready.")


def test_family_tasks_reminders_questions_and_access_log_live(careloop_server) -> None:
    settings = AlexaSimSettings(mcp_url=careloop_server, planner="mock")
    with TestClient(create_alexa_sim_app(settings, planner=MockReplay())) as client:
        client.post("/api/link", json={"account": "maya"})
        client.post("/api/link", json={"account": "sam"})
        say = lambda device, text: client.post("/api/utterance", json={"device_id": device, "text": text}).json()

        say("show", "Alexa, I got a new care plan from my clinic")
        say("show", "Alexa, approve my plan")
        assert say("show", "Alexa, let Sam help with my tasks")["reply"].endswith("Is that right?")
        assert say("show", "yes")["reply"].startswith("Invitation created: Sam can see your tasks and be given tasks to do.")
        assert client.post("/api/invite/open").json()["accepted"] is True

        assigned = say("show", "Alexa, Sam handles my evening task")
        assert assigned["tools"] == ["list_care_tasks", "list_care_circle", "assign_task"]
        assert assigned["reply"].startswith("Done. Sam will handle Complete the evening check-in at 7 PM.")
        reminders = client.get("/api/state").json()["reminders"]
        assert any(r["to"] == "Sam" and r["times"] == ["19:00"] for r in reminders)
        while client.get("/api/state").json()["reminders"]:
            rang = client.post("/api/reminders/ring").json()["rang"]
            if rang["to"] == "Sam":
                break
        dot_turns = [e for e in client.get("/api/state").json()["trace"] if e.get("type") == "turn" and e["device_id"] == "dot"]
        assert dot_turns[-1]["reply"] == "Reminder for Sam: Maya's Complete the evening check-in."

        assert say("dot", "Alexa, what are my tasks for Maya?")["reply"] == \
            "You have 1 task to help Maya with: Complete the evening check-in at 7 PM."
        assert say("dot", "Alexa, I've done Maya's evening task")["reply"] == "Thanks. I've recorded that you did it."

        saved = say("show", "Alexa, add a question for my doctor: can I stop my medicine early")
        assert saved["tools"] == ["add_question_for_clinician"] and saved["reply"].startswith("Saved.")
        assert "medicine" not in saved["reply"].lower()
        assert say("show", "Alexa, get me ready for my appointment")["reply"].endswith(
            "It includes 1 question for your clinician.")
        log = say("show", "Alexa, who has seen my care data this week?")["reply"]
        assert log.startswith("In the last 7 days, Sam") and "completed a task" in log


def test_assigning_a_task_tells_sam_without_the_details_until_he_asks_live(careloop_server) -> None:
    settings = AlexaSimSettings(mcp_url=careloop_server, planner="mock")
    with TestClient(create_alexa_sim_app(settings, planner=MockReplay())) as client:
        client.post("/api/link", json={"account": "maya"})
        client.post("/api/link", json={"account": "sam"})
        say = lambda device, text: client.post("/api/utterance", json={"device_id": device, "text": text}).json()
        state = lambda: client.get("/api/state").json()
        dot = lambda: next(d for d in state()["devices"] if d["id"] == "dot")
        spoken_on_dot = lambda: [a["reply"] for a in client.get("/api/announcements?after=0").json()["items"] if a["device_id"] == "dot"]

        say("show", "Alexa, I got a new care plan from my clinic")
        say("show", "Alexa, approve my plan")
        say("show", "Alexa, let Sam help with my tasks")
        say("show", "yes")
        assert client.post("/api/invite/open").json()["accepted"] is True  # Sam holds see-tasks and do-tasks, not alert rights
        assert "Maya gave you a new task." not in spoken_on_dot()

        # 1. Maya assigns a task: Sam's Dot is told, in generic words, and the ring stays dark.
        say("show", "Alexa, Sam handles my evening task")
        told = spoken_on_dot()
        assert told.count("Maya gave you a new task.") == 1
        assert not any("evening" in line.lower() or "check-in" in line.lower() for line in told if line.startswith("Maya gave"))
        assert dot()["notification"] is False

        # 2. Sam asks for updates: counts only, still no task name.
        updates = say("dot", "Alexa, any CareLoop updates?")["reply"]
        assert updates == "You have 1 new task from Maya." and "evening" not in updates.lower()
        say("show", "Alexa, do my check-in")  # unrelated Maya activity must not announce the same notice again
        assert spoken_on_dot().count("Maya gave you a new task.") == 1

        # 3. Sam asks for the task: the details arrive and the notice clears.
        assert say("dot", "Alexa, what are my tasks for Maya?")["reply"] == \
            "You have 1 task to help Maya with: Complete the evening check-in at 7 PM."
        assert say("dot", "Alexa, any CareLoop updates?")["reply"] == "There are no new CareLoop updates."

        # 4. Repeating the same assignment says nothing new. A different task is told, and "mark it seen"
        #    clears it without any detail.
        say("show", "Alexa, Sam handles my evening task")
        assert say("dot", "Alexa, any CareLoop updates?")["reply"] == "There are no new CareLoop updates."
        say("show", "Alexa, Sam handles my walk task")
        assert spoken_on_dot().count("Maya gave you a new task.") == 2
        assert say("dot", "Alexa, any CareLoop updates?")["reply"] == "You have 1 new task from Maya."
        assert say("dot", "Alexa, mark it seen")["reply"] == "Marked as seen."
        assert say("dot", "Alexa, any CareLoop updates?")["reply"] == "There are no new CareLoop updates."


def test_sams_phone_gets_a_notification_without_detail_and_opens_his_scoped_view_live(careloop_server) -> None:
    settings = AlexaSimSettings(mcp_url=careloop_server, planner="mock")
    with TestClient(create_alexa_sim_app(settings, planner=MockReplay())) as client:
        client.post("/api/link", json={"account": "maya"})
        client.post("/api/link", json={"account": "sam"})
        say = lambda device, text: client.post("/api/utterance", json={"device_id": device, "text": text}).json()
        phone = lambda: client.get("/api/state").json()["phone"]
        say("show", "Alexa, I got a new care plan from my clinic")
        say("show", "Alexa, approve my plan")
        say("show", "Alexa, let Sam help with my tasks")
        say("show", "yes")
        assert client.post("/api/invite/open").json()["accepted"] is True
        assert phone() == {"signed_in": True, "notifications": []}  # nothing waiting yet: no push

        # Maya assigns a task: one notification, in generic words.
        say("show", "Alexa, Sam handles my evening task")
        notes = phone()["notifications"]
        assert [n["text"] for n in notes] == ["Maya gave you a new task."]
        assert "evening" not in str(notes).lower() and "check-in" not in str(notes).lower()
        say("show", "Alexa, do my check-in")  # unrelated activity doesn't push it again
        assert len(phone()["notifications"]) == 1

        # Sam opens it: the tasks view, as Sam. The Dot still never renders a view.
        screen = client.post("/api/phone/open", json={"id": notes[0]["id"]}).json()["screen"]
        assert screen["resource_uri"] == "ui://careloop/tasks" and phone()["notifications"] == []
        assert "html" in client.get("/api/apps/resource", params={"device_id": "phone", "uri": screen["resource_uri"]}).json()
        assert client.get("/api/apps/resource", params={"device_id": "dot", "uri": screen["resource_uri"]}).status_code == 403
        assert say("dot", "Alexa, any CareLoop updates?")["reply"] == "There are no new CareLoop updates."  # opening cleared it

        # A spoken answer that is only counts sends the detail to the phone.
        reply = say("dot", "Alexa, show Maya's tasks")["reply"]
        assert reply.endswith("I've sent the details to your phone.") and "evening" not in reply.lower()
        assert [n["text"] for n in phone()["notifications"]] == ["The details you asked for are ready."]

        client.post("/api/unlink/sam")
        assert phone() == {"signed_in": False, "notifications": []}
        assert client.post("/api/phone/open", json={"id": 1}).status_code == 401


# ---- multi-turn: answer parsing, offers, "it" ------------------------------------------------------
REVIEW_SCHEMA = {"type": "object", "properties": {
    "action": {"anyOf": [{"type": "string", "enum": ["approve", "change time", "skip", "stop"]}, {"type": "null"}]},
    "new_time": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    "who": {"anyOf": [{"type": "string", "enum": ["me", "Sam"]}, {"type": "null"}]}}}


@pytest.mark.parametrize(("text", "expected"), [
    ("yes", {"action": "approve"}), ("sounds good", {"action": "approve"}), ("not now", {"action": "skip"}),
    ("make it 9", {"new_time": "9"}), ("move it to 8 pm", {"action": "change time", "new_time": "8 pm"}),
    ("give it to Sam", {"who": "Sam"}), ("I'll do it myself", {"who": "me"}), ("hmm", {}),
    ("what time is it", {}),  # "me" must not match inside "time"
])
def test_review_answers_are_parsed_like_alexa_would(text, expected) -> None:
    assert parse_answer(text, REVIEW_SCHEMA) == (expected, None)


@pytest.mark.asyncio
async def test_offer_runs_on_yes_and_is_dropped_on_no() -> None:
    offer = {"say": "Want Sam to handle Change the dressing?", "tool": "assign_task",
             "arguments": {"task": "t1", "assignee": "g1"}}
    pool = FakePool(TOOLS + [{"name": "assign_task", "annotations": {}}], {
        "list_care_tasks": ok("You have 1 active task. Want Sam to handle Change the dressing?", next_step=offer),
        "assign_task": lambda args: ok("Done. Sam will handle Change the dressing at 7 PM.",
                                       refs=[{"id": "t1", "kind": "task", "status": "active", "label": "active task 1",
                                              "title": "Change the dressing", "assignee": "Sam", "assignee_id": "g1"}]),
    })
    device = Device("show", DeviceKind.SHOW, "maya", account="maya")
    orchestrator = Orchestrator(pool)
    first = await orchestrator.respond(device, "show my tasks")
    assert first.expects_reply and device.offer["tool"] == "assign_task"
    accepted = await orchestrator.respond(device, "yes please")
    assert pool.calls[-1] == ("assign_task", {"task": "t1", "assignee": "g1"})
    assert accepted.reply.startswith("Done. Sam will handle") and device.offer is None
    assert device.context["task"]["id"] == "t1" and device.context["person"] == {"id": "g1", "name": "Sam"}

    await orchestrator.respond(device, "show my tasks")
    declined = await orchestrator.respond(device, "no thanks")
    assert declined.reply == "Okay." and pool.calls[-1][0] == "list_care_tasks"


@pytest.mark.asyncio
@pytest.mark.parametrize(("text", "task"), [("assign the dressing to Sam", "dressing"),
                                            ("Sam will do the evening walk", "evening walk"),
                                            ("Sam handles it", "t1")])
async def test_mock_assigns_a_named_task_by_its_words(text, task) -> None:
    tasks = {"refs": [{"id": "t1", "kind": "task", "status": "active", "label": "task 1", "times": ["08:00"]}]}
    circle = {"refs": [{"id": "g1", "status": "active", "scopes": ["perform_tasks"]}]}
    steps = [("list_care_tasks", {}, {"structuredContent": tasks}), ("list_care_circle", {}, {"structuredContent": circle})]
    action = await MockReplay().next(text, [{"name": "assign_task"}], [], steps)
    assert (action.tool, action.arguments) == ("assign_task", {"task": task, "assignee": "g1"})


@pytest.mark.asyncio
async def test_it_refers_to_the_last_task_mentioned() -> None:
    pool = FakePool(TOOLS + [{"name": "update_task_time", "annotations": {}}], {
        "update_task_time": lambda args: ok(f"Done. Change the dressing is now at 8 PM."),
    })
    device = Device("show", DeviceKind.SHOW, "maya", account="maya",
                    context={"task": {"id": "t1", "title": "Change the dressing", "times": ["19:00"]}})
    turn = await Orchestrator(pool).respond(device, "Alexa, move it to 8 pm")
    assert pool.calls == [("update_task_time", {"task": "t1", "new_time": "8 pm"})]
    assert turn.reply.startswith("Done. Change the dressing is now at 8 PM.")


def test_multiturn_conversation_end_to_end_live(careloop_server) -> None:
    """Offer → guided review (time change, assign, pause, resume) → 'move it' → chained check-in."""
    settings = AlexaSimSettings(mcp_url=careloop_server, planner="mock")
    with TestClient(create_alexa_sim_app(settings, planner=MockReplay())) as client:
        client.post("/api/link", json={"account": "maya"})
        client.post("/api/link", json={"account": "sam"})
        say = lambda device, text: client.post("/api/utterance", json={"device_id": device, "text": text}).json()

        say("show", "Alexa, let Sam help with my tasks")
        say("show", "yes")
        assert client.post("/api/invite/open").json()["accepted"] is True

        imported = say("show", "Alexa, I got a new care plan from my clinic")
        assert imported["reply"].endswith("Want to go through them now?") and imported["expects_reply"]

        item1 = say("show", "yes")
        assert item1["reply"] == ("Item 1 of 3: Take a short walk, at 8 AM. Approve, change the time, "
                                  "give it to someone, skip, or stop?") and item1["expects_reply"]
        item2 = say("show", "make it 9")
        assert item2["reply"].startswith("Item 2 of 3: Complete the evening check-in, at 7 PM.")
        item3 = say("show", "give it to Sam")
        assert item3["reply"].startswith("Item 3 of 3: Alert rule:") and item3["reply"].endswith("Approve, skip, or stop?")
        paused = say("show", "stop")
        assert paused["reply"].startswith("Okay, I've saved your place. 1 item left.")

        resumed = say("show", "Alexa, continue my review")
        assert resumed["reply"].startswith("Item 3 of 3:")
        done = say("show", "approve")
        assert done["reply"].startswith("Done: 3 approved.")

        mine = say("dot", "Alexa, what are my tasks for Maya?")
        assert mine["reply"] == "You have 1 task to help Maya with: Complete the evening check-in at 7 PM."

        say("show", "Alexa, Sam handles my evening task")  # one task in the reply → "it" now means this task
        moved = say("show", "Alexa, move it to 8 pm")
        assert moved["tools"] == ["update_task_time"]
        assert moved["reply"].startswith("Done. Complete the evening check-in is now at 8 PM.")

        asked = say("show", "Alexa, do my check-in")
        assert asked["reply"].startswith("On a scale from 0 to 10")
        follow = say("show", "four")
        assert follow["reply"] == "Did you do Take a short walk today?"
        summary = say("show", "yes")
        assert summary["reply"].startswith("Check-in recorded. You did 1 of 1 task. Sam has Complete the evening check-in at 8 PM.")

        methods = [e.get("method") for e in client.get("/api/state").json()["trace"]]
        assert methods.count("elicitation/create") >= 4


@pytest.mark.asyncio
async def test_a_stray_yes_with_nothing_pending_is_just_acknowledged() -> None:
    pool = FakePool(TOOLS, {})
    turn = await Orchestrator(pool).respond(Device("show", DeviceKind.SHOW, "maya", account="maya"), "yes")
    assert turn.reply == "Okay." and pool.calls == []


@pytest.mark.asyncio
async def test_new_alexa_request_interrupts_a_waiting_workflow() -> None:
    pool = ElicitingPool()
    pool.accounts["maya"].tools.append({"name": "list_care_tasks", "annotations": {"readOnlyHint": True}})
    pool.responses["list_care_tasks"] = ok("You have 1 active task and 0 active follow-up rules.")
    device = Device("show", DeviceKind.SHOW, "maya", account="maya")
    orchestrator = Orchestrator(pool)
    await orchestrator.respond(device, "Alexa, do my check-in")
    assert device.awaiting is not None
    turn = await orchestrator.respond(device, "Alexa, show my tasks")
    assert pool.answers == [{"action": "decline"}] and device.awaiting is None
    assert turn.reply.startswith("Okay, I skipped today's check-in. Nothing was recorded. You have 1 active task")
    # Without the wake word, the same words would still be read as an answer attempt.
    await orchestrator.respond(device, "Alexa, do my check-in")
    still = await orchestrator.respond(device, "seven")
    assert pool.answers[-1] == {"action": "accept", "content": {"pain_score": 7}} and still.reply.startswith("Check-in recorded.")



def test_wrong_permissions_can_be_refused_before_anything_is_created(careloop_server) -> None:
    settings = AlexaSimSettings(mcp_url=careloop_server, planner="mock")
    with TestClient(create_alexa_sim_app(settings, planner=MockReplay())) as client:
        client.post("/api/link", json={"account": "maya"})
        say = lambda text: client.post("/api/utterance", json={"device_id": "show", "text": text}).json()
        say("Alexa, let Sam help with my tasks")
        refused = say("no")
        assert refused["reply"].startswith("Okay, no invitation was created.")
        assert client.get("/api/state").json()["invitation_pending"] is False



def test_sam_hears_about_the_invitation_on_his_dot(careloop_server) -> None:
    settings = AlexaSimSettings(mcp_url=careloop_server, planner="mock")
    with TestClient(create_alexa_sim_app(settings, planner=MockReplay())) as client:
        client.post("/api/link", json={"account": "maya"})
        client.post("/api/link", json={"account": "sam"})
        say = lambda text: client.post("/api/utterance", json={"device_id": "show", "text": text}).json()
        dot_says = lambda: [e["reply"] for e in client.get("/api/state").json()["trace"]
                            if e.get("type") == "turn" and e["device_id"] == "dot"]

        say("Alexa, let Sam help with my tasks")
        assert dot_says() == []  # nothing until Maya confirms the permissions
        say("yes")
        notice = "Maya invited you to help with her care in CareLoop. Open the invitation in your Alexa app to accept."
        assert dot_says() == [notice]
        assert "task" not in notice.lower()  # who invited him, never what or why

        accepted = client.post("/api/invite/open").json()  # the page speaks this reply on Sam's Dot
        assert accepted["reply"] == "Invitation accepted. You now have the access the patient chose."


def test_sam_hears_a_pending_invitation_when_he_links_later(careloop_server) -> None:
    settings = AlexaSimSettings(mcp_url=careloop_server, planner="mock")
    with TestClient(create_alexa_sim_app(settings, planner=MockReplay())) as client:
        client.post("/api/link", json={"account": "maya"})
        say = lambda text: client.post("/api/utterance", json={"device_id": "show", "text": text}).json()
        say("Alexa, let Sam help with my tasks")
        say("yes")
        client.post("/api/link", json={"account": "sam"})
        replies = [e["reply"] for e in client.get("/api/state").json()["trace"]
                   if e.get("type") == "turn" and e["device_id"] == "dot"]
        assert replies == ["Maya invited you to help with her care in CareLoop. Open the invitation in your Alexa app to accept."]



@pytest.mark.asyncio
async def test_crisis_words_get_emergency_guidance_and_no_tool() -> None:
    pool = FakePool(TOOLS, {})
    turn = await Orchestrator(pool).respond(Device("show", DeviceKind.SHOW, "maya", account="maya"),
                                            "Alexa, I don't want to live anymore")
    assert pool.calls == [] and "988" in turn.reply and "local emergency number" in turn.reply


def test_first_use_consent_then_the_original_request_runs_live(careloop_server_with_consent) -> None:
    settings = AlexaSimSettings(mcp_url=careloop_server_with_consent, planner="mock")
    with TestClient(create_alexa_sim_app(settings, planner=MockReplay())) as client:
        client.post("/api/link", json={"account": "maya"})
        say = lambda text: client.post("/api/utterance", json={"device_id": "show", "text": text}).json()
        first = say("Alexa, show my tasks")
        assert first["reply"].startswith("Before I save anything: CareLoop keeps your care plan")
        assert first["reply"].endswith("Is that okay?") and first["expects_reply"]
        agreed = say("yes")
        assert agreed["tools"] == ["accept_data_use", "list_care_tasks"]
        assert agreed["reply"].startswith("Thanks, you're all set. You have no CareLoop plan items yet.")
        assert say("Alexa, show my tasks")["reply"].startswith("You have no CareLoop plan items yet.")  # asked once
        named = say("Alexa, call me Maya")
        assert named["tools"] == ["set_my_details"] and named["reply"] == "Done. I'll call you Maya."


def test_demo_reset_restores_the_seeded_day_and_links_both_devices(careloop_server) -> None:
    settings = AlexaSimSettings(mcp_url=careloop_server, planner="mock")
    with TestClient(create_alexa_sim_app(settings, planner=MockReplay())) as client:
        client.post("/api/link", json={"account": "maya"})
        say = lambda text: client.post("/api/utterance", json={"device_id": "show", "text": text}).json()
        say("Alexa, remove Sam")  # leaves a confirmation waiting
        out = client.post("/api/demo/reset").json()
        assert out["seeded"]["care_circle"] == ["Sam"]
        state = client.get("/api/state").json()
        assert {d["id"]: d["account"] for d in state["devices"]} == {"show": "maya", "dot": "sam"}
        assert not any(d["pending"] for d in state["devices"])
        assert [e["text"] for e in state["trace"] if e.get("type") == "host"][-1].startswith("Demo reset")
        reply = say("Alexa, who has access to my care?")["reply"]
        assert "1 active caregiver" in reply  # Sam, from the seed


def test_idle_demo_resets_itself(careloop_server) -> None:
    settings = AlexaSimSettings(mcp_url=careloop_server, planner="mock", idle_reset_minutes=0.01)
    with TestClient(create_alexa_sim_app(settings, planner=MockReplay())) as client:
        client.post("/api/link", json={"account": "maya"})
        for _ in range(50):
            if any(str(e.get("text", "")).startswith("Demo reset") for e in client.get("/api/state").json()["trace"]):
                break
            time.sleep(0.2)
        else:
            pytest.fail("the idle demo did not reset")


class SayThenCall:
    """A stub planner: the first request gets a spoken question, the next one calls a tool."""
    name = "stub"

    def __init__(self) -> None:
        self.seen: list[str] = []

    async def next(self, utterance, tools, history, steps, context=None):
        from alexa_sim.planners import Action
        self.seen.append(utterance)
        if steps:
            return Action(say="Done.")
        if utterance == "yes":
            return Action(tool="list_care_tasks", arguments={})
        return Action(say="Do you want me to check your tasks?")


@pytest.mark.asyncio
async def test_a_bare_yes_reaches_the_planner_after_the_assistant_asked_a_question() -> None:
    pool = FakePool(TOOLS, {"list_care_tasks": ok("You have 2 active tasks.")})
    planner = SayThenCall()
    orchestrator = Orchestrator(pool, planner, fallback=None)
    device = Device("show", DeviceKind.SHOW, "maya", account="maya")
    first = await orchestrator.respond(device, "Alexa, what is on my list?")
    assert first.reply.endswith("?")
    second = await orchestrator.respond(device, "yes")
    assert planner.seen[-1] == "yes" and pool.calls == [("list_care_tasks", {})]
    assert second.reply != "Okay."


@pytest.mark.asyncio
async def test_a_bare_yes_with_nothing_asked_is_still_just_okay() -> None:
    pool = FakePool(TOOLS, {})
    planner = SayThenCall()
    turn = await Orchestrator(pool, planner, fallback=None).respond(Device("show", DeviceKind.SHOW, "maya", account="maya"), "yes")
    assert turn.reply == "Okay." and planner.seen == []


def test_the_inspector_records_exactly_what_the_device_heard() -> None:
    class Pool:
        accounts = {}
        def linked(self, account): return False
        async def close(self): pass
    with TestClient(create_alexa_sim_app(AlexaSimSettings(), pool=Pool(), planner=MockReplay())) as client:
        client.post("/api/utterance", json={"device_id": "show", "text": "Fine."})
        turns = [e for e in client.get("/api/state").json()["trace"] if e.get("type") == "turn"]
    assert turns and turns[-1]["heard"] == "Fine."


# ---- a spoken announcement is part of the conversation, so a following "yes" has something to refer to ------------
REVIEW_TOOLS = TOOLS + [{"name": "review_plan_by_voice", "annotations": {"readOnlyHint": False},
                         "_meta": {"ui": {"resourceUri": "ui://careloop/plan-review"}}}]
DOC_READY = "Your document is ready. 8 items need your approval. Want to go through them now?"
GO_THROUGH = {"tool": "review_plan_by_voice", "arguments": {}, "retry_text": None}


class RecordingPlanner:
    """A stand-in model that reads the conversation memory: it says yes to the question it was just asked."""
    name = "recording"

    def __init__(self) -> None:
        self.histories: list[list[dict]] = []

    async def next(self, utterance, tools, history, steps, context=None):
        from alexa_sim.planners import Action
        self.histories.append(list(history))
        if steps:
            return Action(say="Done.")
        asked = next((m["content"] for m in reversed(history) if m.get("role") == "assistant"), "")
        if utterance.lower().startswith("yes") and "go through them" in str(asked).lower():
            return Action(tool="review_plan_by_voice", arguments={})
        return Action(say="Sorry, I didn't catch that.")


def test_device_remembers_what_it_said_and_caps_its_memory() -> None:
    device = Device("show", DeviceKind.SHOW, "maya", account="maya")
    device.said(DOC_READY, GO_THROUGH)
    assert device.history == [{"role": "assistant", "content": DOC_READY}] and device.offer == GO_THROUGH
    device.said("")  # nothing spoken, nothing remembered
    assert len(device.history) == 1
    for n in range(60):
        device.said(f"Reminder {n}.")
    assert len(device.history) == 40 and device.offer is None


@pytest.mark.asyncio
async def test_yes_after_a_document_ready_announcement_runs_the_review() -> None:
    pool = FakePool(REVIEW_TOOLS, {"review_plan_by_voice": ok("Item 1 of 4: Take a short walk.", view="ui://careloop/plan-review")})
    device = Device("show", DeviceKind.SHOW, "maya", account="maya")
    device.said(DOC_READY, GO_THROUGH)
    turn = await Orchestrator(pool, RecordingPlanner(), fallback=None).respond(device, "yes")
    assert pool.calls == [("review_plan_by_voice", {})] and turn.reply.startswith("Item 1 of 4")


@pytest.mark.asyncio
async def test_the_model_understands_yes_from_conversation_memory_alone() -> None:
    """No stored offer: the planner must be reached and must see the announcement in the history it is given."""
    pool = FakePool(REVIEW_TOOLS, {"review_plan_by_voice": ok("Item 1 of 4: Take a short walk.", view="ui://careloop/plan-review")})
    device = Device("show", DeviceKind.SHOW, "maya", account="maya")
    device.said(DOC_READY)  # announcement remembered, but no offer
    planner = RecordingPlanner()
    turn = await Orchestrator(pool, planner, fallback=None).respond(device, "yes")
    assert planner.histories and planner.histories[0][0] == {"role": "assistant", "content": DOC_READY}
    assert pool.calls == [("review_plan_by_voice", {})] and turn.reply.startswith("Item 1 of 4")


@pytest.mark.asyncio
async def test_yes_with_nothing_said_is_still_just_okay() -> None:
    device = Device("show", DeviceKind.SHOW, "maya", account="maya")
    planner = RecordingPlanner()
    turn = await Orchestrator(FakePool(REVIEW_TOOLS, {}), planner, fallback=None).respond(device, "yes")
    assert turn.reply == "Okay." and planner.histories == []


def test_openai_history_never_opens_with_an_assistant_message() -> None:
    from alexa_sim.planners import _openai_history
    out = _openai_history([{"role": "assistant", "content": DOC_READY}])
    assert out[0]["role"] == "user" and out[1] == {"role": "assistant", "content": DOC_READY}
    plain = _openai_history([{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}])
    assert [m["role"] for m in plain] == ["user", "assistant"]  # a normal conversation is untouched
