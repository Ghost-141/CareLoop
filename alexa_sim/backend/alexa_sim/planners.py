"""Planners choose the next tool call from the *discovered* MCP tool list.

``OllamaPlanner`` is the Alexa+-like path: the model sees only tool names,
descriptions and input schemas from ``tools/list`` and decides what to call.
``MockReplay`` is a deterministic stage fallback for the scripted demo
utterances; it still only picks tools the server actually advertised.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.request import Request, urlopen

from .reply_policy import structured

Step = tuple[str, dict[str, Any], dict[str, Any]]  # (tool, arguments, normalized result)

SYSTEM_PROMPT = """You are a voice assistant on a smart speaker, simulating Alexa+ calling the CareLoop add-on through MCP tools.
Rules:
- Use CareLoop tools for care-plan tasks, check-ins, the care circle, caregiver updates, handoffs and records.
- Tool results contain only `speakable`, `status`, `refs` (opaque ids with labels like "draft task 1") and a view link. Pass ref ids back to action tools. Never invent ids: look them up with a list tool first.
- For "do my check-in" (no value given) call start_daily_checkin with no arguments: CareLoop asks the person its own follow-up questions. Never ask for check-in values yourself.
- If the person states a pain score directly, use record_pain_observation with that integer 0-10 and a fresh unique idempotency_key.
- "Add a question for my doctor: ..." → add_question_for_clinician with the question text. Never answer the question yourself.
- To assign a task to a family member, look up the task (list_care_tasks) and the person (list_care_circle), then call assign_task.
- A family member asking about their own tasks → list_my_assigned_tasks; when they say they did one → record_task_completion with its id.
- Never give medical advice, diagnosis, dosage or emergency guidance. For those, do not call a tool; say CareLoop can't advise on that and to contact their clinician (or emergency services in an emergency).
- When you have the result you need, stop calling tools and answer in one short spoken sentence."""

DEMO_PLAN_TITLE = "Synthetic discharge plan (demo only)"
DEMO_PLAN_TEXT = "\n".join((
    "TASK: Take a short walk | schedule: morning",
    "TASK: Complete the evening check-in | schedule: evening",
    "RULE: PAIN_SCORE_AT_OR_ABOVE threshold=7 consecutive_days=2",
))


@dataclass
class Action:
    tool: str | None = None
    arguments: dict[str, Any] | None = None
    say: str | None = None  # a final spoken answer when no tool is needed


class Planner(Protocol):
    name: str

    async def next(self, utterance: str, tools: list[dict[str, Any]], history: list[dict[str, str]],
                   steps: list[Step]) -> Action: ...


def _refs(steps: list[Step], tool: str | None = None) -> list[dict[str, Any]]:
    for name, _args, result in reversed(steps):
        if tool is None or name == tool:
            refs = structured(result).get("refs")
            return refs if isinstance(refs, list) else []
    return []


def _called(steps: list[Step], tool: str, key: str) -> set[str]:
    return {str(args.get(key)) for name, args, _ in steps if name == tool}


class MockReplay:
    """Deterministic planner for the synthetic demo script."""

    name = "mock"

    async def next(self, utterance: str, tools: list[dict[str, Any]], history: list[dict[str, str]],
                   steps: list[Step]) -> Action:
        available = {str(tool.get("name")) for tool in tools}
        text = utterance.lower()
        action = self._plan(text, steps)
        if action.tool and action.tool not in available:
            return Action(say="CareLoop can't do that from this account.")
        return action

    def _plan(self, text: str, steps: list[Step]) -> Action:
        first = not steps
        question = re.search(r"\b(?:question|ask)\b.*?\b(?:doctor|clinician|nurse|care team)\b[:,]?\s*(.*)$", text)
        if question:
            asked = question.group(1).strip(" .?!") or text
            return Action("add_question_for_clinician", {"question": asked[:300] + "?"}) if first else Action()
        if re.search(r"\bwho\b.*\b(seen|accessed|looked|viewed|checked)\b", text):
            return Action("who_accessed_my_care_data", {}) if first else Action()
        if re.search(r"\b(done|did|finished|completed)\b.*\bmaya'?s\b|\bmaya'?s\b.*\b(is )?(done|finished)\b", text):
            return self._each(steps, "list_my_assigned_tasks", "record_task_completion", "task_id",
                              lambda r: r.get("kind") == "task", limit=1)
        if re.search(r"\btasks? for maya\b|\bwhat do i need to do\b|\bassigned to me\b|\bmy (assigned )?tasks\b.*\bmaya\b", text):
            return Action("list_my_assigned_tasks", {}) if first else Action()
        assignee = re.search(r"\b(sam|mom|dad|brother|sister)\b", text)
        if assignee and re.search(r"\b(handles?|assign|takes? care of|will do|is doing|do my)\b", text) and "invite" not in text:
            return self._assign(text, steps)
        if re.search(r"\b(new|import|got)\b.*\b(care )?plan\b", text):
            return Action("import_care_plan_text", {"title": DEMO_PLAN_TITLE, "text": DEMO_PLAN_TEXT}) if first else Action()
        if "approve" in text:
            return self._each(steps, "list_care_tasks", "approve_plan_item", "record_id", lambda r: r.get("status") == "draft")
        if re.search(r"\b(done|completed|finished|did)\b", text) and re.search(r"\b(walk|tasks?)\b", text):
            return self._each(steps, "list_care_tasks", "record_task_completion", "task_id",
                              lambda r: r.get("kind") == "task" and r.get("status") == "active", limit=1)
        if re.search(r"\b(invite|add|let|share with)\b", text) and re.search(r"\b(sam|brother|caregiver|care circle)\b", text):
            if not first:
                return Action()
            scopes = ["read_tasks"] if "task" in text else []
            if re.search(r"\b(update|alert|notif)", text) or not scopes:
                scopes += ["receive_alerts", "acknowledge_alerts"]
            if re.search(r"\b(upload|document|prescription)", text):
                scopes.append("upload_documents")
            if re.search(r"\b(help|handle|do|perform)\b.*\btasks?\b", text):
                scopes.append("perform_tasks")
            arguments: dict[str, Any] = {"scopes": scopes}
            named = re.search(r"\b(sam|mom|dad)\b", text)
            if named:
                arguments["name"] = named.group(1).capitalize()
            weeks = re.search(r"\b(one|two|three|four|\d+) weeks?\b", text)
            if weeks:
                count = {"one": 1, "two": 2, "three": 3, "four": 4}.get(weeks.group(1)) or int(weeks.group(1))
                arguments["expires_at"] = time.strftime("%Y-%m-%d", time.gmtime(time.time() + count * 7 * 86_400))
            return Action("invite_caregiver", arguments)
        if re.search(r"\b(document|prescription|upload|what needs approv|needs? (my )?approval)", text) and not re.search(r"\b(invite|let|share with)\b", text):
            return Action("get_intake_status", {}) if first else Action()
        if re.search(r"\b(remove|revoke|stop sharing)\b", text):
            return self._each(steps, "list_care_circle", "revoke_caregiver", "invitation_id",
                              lambda r: r.get("status") in {"active", "pending"}, limit=1)
        if re.search(r"\b(who has access|care circle)\b", text):
            return Action("list_care_circle", {}) if first else Action()
        if re.search(r"\b(mark it seen|acknowledge|got it|mark .* seen)\b", text):
            return self._each(steps, "list_generic_notifications", "acknowledge_alert", "alert_id",
                              lambda r: r.get("status") == "action_required")
        if re.search(r"\b(check.?in|pain)\b", text) and re.search(r"\b(\d{1,2})\b", text) and "what" not in text:
            if not first:
                return Action()
            score = int(re.search(r"\b(\d{1,2})\b", text).group(1))
            arguments = {"pain_score": score, "idempotency_key": uuid.uuid4().hex}
            if "yesterday" in text:
                arguments["observed_at"] = int(time.time()) - 86_400
            return Action("record_pain_observation", arguments)
        if re.search(r"\bcheck.?in\b", text) and not re.search(r"\d", text):
            # CareLoop asks its own follow-up question through MCP elicitation.
            return Action("start_daily_checkin", {}) if first else Action()
        if re.search(r"\bwhat\b.*\bpain\b|\bpain score\b", text):
            return Action("list_care_records", {"record_type": "OBSERVATION"}) if first else Action()
        if re.search(r"\b(handoff|appointment|visit|doctor)\b", text):
            return Action("create_visit_handoff", {"from_date": "last_7_days"}) if first else Action()
        if re.search(r"\b(notification|update)s?\b", text):
            return Action("list_generic_notifications", {}) if first else Action()
        if "export" in text:
            return Action("export_care_data", {}) if first else Action()
        if re.search(r"\b(tasks?|plan|to do|todo)\b", text):
            return Action("list_care_tasks", {}) if first else Action()
        if first:
            return Action(say="Sorry, I can't help with that in CareLoop yet.")
        return Action()

    @staticmethod
    def _assign(text: str, steps: list[Step]) -> Action:
        """Find the task (by time of day) and the family member, then assign."""
        called = {name for name, _, _ in steps}
        if "list_care_tasks" not in called:
            return Action("list_care_tasks", {})
        if "list_care_circle" not in called:
            return Action("list_care_circle", {})
        if "assign_task" in called:
            return Action()
        tasks = [r for r in _refs(steps, "list_care_tasks") if r.get("kind") == "task" and r.get("status") == "active"]
        if "evening" in text or "night" in text:
            tasks = [r for r in tasks if any(t >= "17:00" for t in r.get("times", []))] or tasks
        elif "morning" in text:
            tasks = [r for r in tasks if any(t < "12:00" for t in r.get("times", []))] or tasks
        people = [r for r in _refs(steps, "list_care_circle")
                  if r.get("status") == "active" and "perform_tasks" in r.get("scopes", [])]
        if not tasks:
            return Action(say="There's no active task to assign yet.")
        if not people:
            return Action(say="No family member can be assigned tasks yet. Invite them to help with tasks first.")
        return Action("assign_task", {"task_id": tasks[0]["id"], "assignee_id": people[0]["id"]})

    @staticmethod
    def _each(steps: list[Step], lookup: str, act: str, key: str, want, limit: int | None = None) -> Action:
        """Look up refs once, then act on each matching ref (optionally only ``limit`` of them)."""
        if not any(name == lookup for name, _, _ in steps):
            return Action(lookup, {})
        done = _called(steps, act, key)
        if limit is not None and len(done) >= limit:
            return Action()
        for ref in _refs(steps, lookup):
            if want(ref) and str(ref.get("id")) not in done:
                return Action(act, {key: ref["id"]})
        if not done:
            return Action(say="I couldn't find anything to do that for.")
        return Action()


class OllamaPlanner:
    """Native tool-calling through a local Ollama model."""

    name = "ollama"

    def __init__(self, base_url: str, model: str, timeout: float = 60.0, post=None) -> None:
        self.base_url, self.model, self.timeout = base_url.rstrip("/"), model, timeout
        self._post = post or self._http_post

    async def next(self, utterance: str, tools: list[dict[str, Any]], history: list[dict[str, str]],
                   steps: list[Step]) -> Action:
        messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}, *history,
                                          {"role": "user", "content": utterance}]
        for name, arguments, result in steps:
            messages.append({"role": "assistant", "content": "",
                             "tool_calls": [{"function": {"name": name, "arguments": arguments}}]})
            # Only the voice-safe contract (or a generic error) is shown to the model.
            visible = ({"error": result.get("text") or "unavailable"} if result.get("isError")
                       else {k: v for k, v in structured(result).items() if k in {"status", "speakable", "refs"}})
            messages.append({"role": "tool", "tool_name": name, "content": json.dumps(visible)})
        payload = {
            "model": self.model, "stream": False, "think": False, "messages": messages,
            "options": {"temperature": 0},
            "tools": [{"type": "function", "function": {
                "name": tool["name"], "description": tool.get("description", ""),
                "parameters": tool.get("inputSchema") or {"type": "object", "properties": {}}}} for tool in tools],
        }
        raw = await asyncio.to_thread(self._post, f"{self.base_url}/api/chat", json.dumps(payload).encode("utf-8"))
        message = json.loads(raw.decode("utf-8")).get("message", {})
        calls = message.get("tool_calls") or []
        if calls:
            function = calls[0].get("function", {})
            arguments = function.get("arguments") or {}
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {}
            return Action(str(function.get("name", "")), arguments if isinstance(arguments, dict) else {})
        return Action(say=(message.get("content") or "").strip() or None)

    def _http_post(self, url: str, body: bytes) -> bytes:
        request = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - configured local model URL
            return response.read()
