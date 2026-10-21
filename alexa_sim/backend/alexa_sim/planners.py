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
- If the person states a pain score directly, use record_pain_observation with that integer 0-10. Spelled-out numbers count ("four" is 4). Never ask the person for any other field, such as a key or an id.
- "Add a question for my doctor: ..." → add_question_for_clinician with the question text. Never answer the question yourself.
- To give a task to a family member, call assign_task with task = the task's name as they said it (e.g. "the dressing") and assignee = the person's name (e.g. "Sam"). For update_task_time, task = the name too. Only use an id for "it" / "that one".
- The patient asking about their tasks or plan ("what's on my plan?") → list_care_tasks. Asking which medicines they take or when ("what medicine do I take before breakfast?", "when do I take omeprazole?") → list_care_tasks with medicines true, and when set to the meal or part of the day they named ("breakfast", "dinner", "morning", "bedtime"). Speak its answer as given; never add a medicine, time or instruction of your own. A family member asking about tasks they help with → list_my_assigned_tasks; when they say they did one → record_task_completion with its id.
- "Go through them" / "continue my review" → review_plan_by_voice. "Move it to 8 pm" → update_task_time on the task just mentioned.
- If someone mentions self-harm or a medical emergency, call no tool: tell them to call their local emergency number (988 in the US).
- Only for removing a caregiver or deleting a record (other tools, like assign_task and update_task_time, take names as the person said them, with no lookup): call the tool IMMEDIATELY. The host, not you, asks the person to confirm, so never write a confirmation question yourself. Example: "remove Sam" → call revoke_caregiver with caregiver "Sam" and say nothing else. "Delete my last pain record" → call list_care_records, then delete_care_record with the ref labelled "latest pain check-in". Never ask the person for an id.
- Any question about the patient's records, scores or history, from the patient OR a family member, must go through a CareLoop tool (search_care_history or list_care_records). Always call the tool first, then speak only what it returns, whatever it says: the server decides who may hear what. Never ask who the person is or ask for clarification. Example: "what was Maya's pain score?" → search_care_history with query "pain score".
- "Get me ready for my appointment" / "prepare for my doctor visit" / "a summary for my clinician" → create_visit_handoff with from_date "last_7_days". export_care_data is only for exporting, downloading or getting a copy of all their data.
- "Who has access to my care" / "who can see my tasks" → list_care_circle. "Who has seen my data" / "who looked at my records" → who_accessed_my_care_data.
- "Anything I should know" / "anything coming up" / "what needs my attention" / "what's next" → get_suggestions. Speak only what it returns, never add a suggestion of your own, and when nothing applies say so. If it asks a question, the person's "yes" runs that step. "What do I need to do today" is the task list (list_care_tasks), not get_suggestions.
- "Turn suggestions off" / "turn suggestions on" → set_my_details with suggestions false / true.
- "Check I understood my plan" / "quiz me on my plan" / "teach-back" / "check my understanding" → start_teach_back with no arguments. CareLoop asks its own questions and checks the answers; never ask or judge them yourself. It is not the daily check-in and not the task list.
- "Call me Maya" / "my time zone is …" → set_my_details.
- Never give medical advice, diagnosis, dosage or emergency guidance. For those, do not call a tool; say CareLoop can't advise on that and to contact their clinician (or emergency services in an emergency).
- If someone says they got or shared a care plan, prescription or document but doesn't give its text, never import text: call get_intake_status first, which says whether a shared document is being read or is ready. Only if CareLoop says none has been shared, ask them to share it in the Alexa app.
- Act when you have what a tool requires. Don't ask about optional details (like an expiry date); leave them out.
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
                   steps: list[Step], context: dict[str, Any] | None = None) -> Action: ...


def _refs(steps: list[Step], tool: str | None = None) -> list[dict[str, Any]]:
    for name, _args, result in reversed(steps):
        if tool is None or name == tool:
            refs = structured(result).get("refs")
            return refs if isinstance(refs, list) else []
    return []


def _time_phrase(text: str) -> str | None:
    from .orchestrator import time_phrase
    return time_phrase(text)


def _called(steps: list[Step], tool: str, key: str) -> set[str]:
    return {str(args.get(key)) for name, args, _ in steps if name == tool}


class MockReplay:
    """Deterministic planner for the synthetic demo script."""

    name = "mock"

    async def next(self, utterance: str, tools: list[dict[str, Any]], history: list[dict[str, str]],
                   steps: list[Step], context: dict[str, Any] | None = None) -> Action:
        available = {str(tool.get("name")) for tool in tools}
        text = utterance.lower()
        action = self._plan(text, steps, context or {})
        if action.tool and action.tool not in available:
            return Action(say="CareLoop can't do that from this account.")
        return action

    def _plan(self, text: str, steps: list[Step], context: dict[str, Any] | None = None) -> Action:
        first, context = not steps, context or {}
        if re.search(r"\b(continue|resume|finish)\b.*\breview\b|\bgo through (them|my plan|the items|it)\b"
                     r"|\breview (my plan|them|the items) (by voice|one by one)\b", text):
            return Action("review_plan_by_voice", {}) if first else Action()
        refers = re.search(r"\b(it|that|this|that one|this one)\b", text)
        spoken = _time_phrase(text)
        if refers and spoken and re.search(r"\b(move|change|make|shift|reschedule|push)\b", text) and context.get("task"):
            return Action("update_task_time", {"task": context["task"]["id"], "new_time": spoken}) if first else Action()
        if refers and re.search(r"\b(give|assign|hand)\b.*\bto\b", text) and context.get("task"):
            return self._give(text, steps, context)
        named = re.search(r"\b(?:call me|my name is)\s+([a-z][a-z' -]{0,30})", text)
        if named:
            return Action("set_my_details", {"name": named.group(1).strip().title()}) if first else Action()
        switch = re.search(r"\bturn (?:my )?suggestions (on|off)\b", text)
        if switch:
            return Action("set_my_details", {"suggestions": switch.group(1) == "on"}) if first else Action()
        if re.search(r"\bteach.?back\b|\bquiz me\b|\bcheck (that )?i (understood|understand|got)\b"
                     r"|\bcheck my understanding\b|\btest me on my plan\b", text):
            return Action("start_teach_back", {}) if first else Action()
        if re.search(r"\banything (i should know|coming up|i need to know)\b|\bwhat'?s next\b|\bwhat needs my attention\b"
                     r"|\bany suggestions\b", text):
            return Action("get_suggestions", {}) if first else Action()
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
            return Action("acknowledge_alert", {}) if first else Action()  # one call marks everything waiting as seen
        if re.search(r"\b(check.?in|pain)\b", text) and re.search(r"\b(\d{1,2})\b", text) and "what" not in text:
            if not first:
                return Action()
            score = int(re.search(r"\b(\d{1,2})\b", text).group(1))
            arguments = {"pain_score": score, "idempotency_key": uuid.uuid4().hex}
            if "yesterday" in text:
                arguments["observed_at"] = int(time.time()) - 86_400
            return Action("record_pain_observation", arguments)
        if re.search(r"\b(medicines?|medications?|meds|pills?)\b|\bwhen do i take\b", text):
            when = re.search(r"\b(breakfast|lunch|dinner|supper|bedtime|morning|afternoon|evening|night)\b", text)
            arguments = {"medicines": True} | ({"when": when.group(1)} if when else {})
            return Action("list_care_tasks", arguments) if first else Action()
        if re.search(r"\bcheck.?in\b", text) and not re.search(r"\d", text):
            # CareLoop asks its own follow-up question through MCP elicitation.
            return Action("start_daily_checkin", {}) if first else Action()
        if re.search(r"\bwhat\b.*\bpain\b|\bpain score\b", text):
            return Action("list_care_records", {"record_type": "OBSERVATION"}) if first else Action()
        if re.search(r"\b(handoff|appointment|visit|doctor)\b", text):
            return Action("create_visit_handoff", {"from_date": "last_7_days"}) if first else Action()
        if re.search(r"\b(notification|update)s?\b|\bwhat'?s new\b", text):
            return Action("list_generic_notifications", {}) if first else Action()
        if "export" in text:
            return Action("export_care_data", {}) if first else Action()
        if re.search(r"\b(tasks?|plan|to do|todo|rules?)\b", text):
            return Action("list_care_tasks", {}) if first else Action()
        if first:
            return Action(say="Sorry, I can't help with that in CareLoop yet.")
        return Action()

    @staticmethod
    def _give(text: str, steps: list[Step], context: dict[str, Any]) -> Action:
        """ "Give it to Sam" / "give that one to him": the remembered task, a named or remembered person."""
        if any(name == "assign_task" for name, _, _ in steps):
            return Action()
        named = re.search(r"\b(sam|mom|dad)\b", text)
        person = context.get("person")
        if person and (not named or (person.get("name") or "").lower() == named.group(1)):
            return Action("assign_task", {"task": context["task"]["id"], "assignee": person["id"]})
        if not any(name == "list_care_circle" for name, _, _ in steps):
            return Action("list_care_circle", {})
        wanted = named.group(1) if named else None
        match = next((r for r in _refs(steps, "list_care_circle") if r.get("status") == "active"
                      and (wanted is None or (r.get("name") or "").lower() == wanted)), None)
        if not match:
            return Action(say="I couldn't find who you mean in your care circle.")
        return Action("assign_task", {"task": context["task"]["id"], "assignee": match["id"]})

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
        # Refs carry no task text, so a task named in the request ("the dressing") goes to
        # CareLoop as words and the server resolves it; otherwise pick by time of day.
        phrase = re.search(r"\b(?:assign|give|hand)\s+(?:the\s+|my\s+)?(.+?)\s+to\s+\w+|"
                           r"\b(?:handles?|takes? care of|will do|is doing)\s+(?:the\s+|my\s+)?(.+?)$", text)
        named = next((g for g in (phrase.groups() if phrase else ()) if g), "").strip(" .?!")
        if named and named not in {"it", "that", "that one", "this", "evening task", "morning task", "task"}:
            return Action("assign_task", {"task": named, "assignee": people[0]["id"]})
        return Action("assign_task", {"task": tasks[0]["id"], "assignee": people[0]["id"]})

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


def _context_note(context: dict[str, Any]) -> str:
    parts = []
    task, person = context.get("task"), context.get("person")
    if task:
        when = f" at {', '.join(task.get('times') or [])}" if task.get("times") else ""
        parts.append(f"task '{task.get('title') or 'task'}'{when} (id={task['id']})")
    if person:
        parts.append(f"person '{person.get('name') or 'family member'}' (id={person['id']})")
    return ("Recently mentioned; use these ids when the person says it, that one, him or her: " + "; ".join(parts) + ".") if parts else ""


def chat_completions_url(base_url: str) -> str:
    """Accept a base ('https://host/v1'), a bare host, or the full '.../v1/chat/completions' URL."""
    url = base_url.strip().rstrip("/")
    if url.endswith("/chat/completions"):
        return url
    return f"{url}/chat/completions" if url.endswith("/v1") else f"{url}/v1/chat/completions"


def _openai_history(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The device keeps tool calls in Ollama's shape (no ids, arguments as an object, ``tool_name``).
    OpenAI-compatible endpoints need call ids, JSON-string arguments and ``tool_call_id``."""
    converted: list[dict[str, Any]] = []
    waiting: list[str] = []
    for message in history:
        if message.get("role") == "assistant" and message.get("tool_calls"):
            calls = []
            for call in message["tool_calls"]:
                function = call.get("function", {})
                call_id = f"hist_{len(converted)}_{len(calls)}"
                waiting.append(call_id)
                arguments = function.get("arguments") or {}
                calls.append({"id": call_id, "type": "function", "function": {
                    "name": function.get("name", ""),
                    "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments)}})
            converted.append({"role": "assistant", "content": None, "tool_calls": calls})
        elif message.get("role") == "tool":
            converted.append({"role": "tool", "tool_call_id": waiting.pop(0) if waiting else "hist_unknown",
                              "content": message.get("content", "")})
        else:
            converted.append({"role": message.get("role", "user"), "content": message.get("content", "")})
    if converted and converted[0]["role"] == "assistant":
        # An announcement can open the memory. Several gateways need the first message to be the user's.
        converted.insert(0, {"role": "user", "content": "(Alexa spoke first, without being asked.)"})
    return converted


class OpenAIPlanner:
    """Tool-calling through any OpenAI-compatible chat completions endpoint (OpenAI, a gateway, vLLM, LM Studio…).

    Like the Ollama planner, the model sees only the voice-safe parts of tool results.
    """

    name = "openai"

    def __init__(self, base_url: str, model: str, api_key: str = "", timeout: float = 60.0, post=None) -> None:
        self.url, self.model, self.api_key, self.timeout = chat_completions_url(base_url), model, api_key, timeout
        self._post = post or self._http_post

    async def next(self, utterance: str, tools: list[dict[str, Any]], history: list[dict[str, str]],
                   steps: list[Step], context: dict[str, Any] | None = None) -> Action:
        today = time.strftime("%A %Y-%m-%d", time.localtime())
        # One system message, first: many endpoints (Claude-backed gateways among them) reject a later one.
        system = "\n".join(part for part in (f"{SYSTEM_PROMPT}\nToday is {today}.", _context_note(context or {})) if part)
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}, *_openai_history(history)]
        messages.append({"role": "user", "content": utterance})
        for index, (name, arguments, result) in enumerate(steps):
            call_id = f"step_{index}"
            messages.append({"role": "assistant", "content": None, "tool_calls": [
                {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}]})
            visible = ({"error": result.get("text") or "unavailable"} if result.get("isError")
                       else {k: v for k, v in structured(result).items() if k in {"status", "speakable", "refs"}})
            messages.append({"role": "tool", "tool_call_id": call_id, "content": json.dumps(visible)})
        payload = {
            "model": self.model, "messages": messages, "temperature": 0,
            "tools": [{"type": "function", "function": {
                "name": tool["name"], "description": tool.get("description", ""),
                "parameters": tool.get("inputSchema") or {"type": "object", "properties": {}}}} for tool in tools],
        }
        raw = await asyncio.to_thread(self._post, self.url, json.dumps(payload).encode("utf-8"))
        message = (json.loads(raw.decode("utf-8")).get("choices") or [{}])[0].get("message") or {}
        calls = message.get("tool_calls") or []
        if calls:
            function = calls[0].get("function", {})
            arguments = function.get("arguments") or {}
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments or "{}")
                except json.JSONDecodeError:
                    arguments = {}
            return Action(str(function.get("name", "")), arguments if isinstance(arguments, dict) else {})
        content = message.get("content")
        if isinstance(content, list):  # some gateways return content parts
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        return Action(say=(content or "").strip() or None)

    def _http_post(self, url: str, body: bytes) -> bytes:
        headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {})}
        request = Request(url, data=body, headers=headers, method="POST")
        with urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - the operator's configured model URL
            return response.read()


class OllamaPlanner:
    """Native tool-calling through a local Ollama model."""

    name = "ollama"

    def __init__(self, base_url: str, model: str, timeout: float = 60.0, post=None) -> None:
        self.base_url, self.model, self.timeout = base_url.rstrip("/"), model, timeout
        self._post = post or self._http_post

    async def next(self, utterance: str, tools: list[dict[str, Any]], history: list[dict[str, str]],
                   steps: list[Step], context: dict[str, Any] | None = None) -> Action:
        today = time.strftime("%A %Y-%m-%d", time.localtime())
        messages: list[dict[str, Any]] = [{"role": "system", "content": f"{SYSTEM_PROMPT}\nToday is {today}."}, *history]
        note = _context_note(context or {})
        if note:
            messages.append({"role": "system", "content": note})
        messages.append({"role": "user", "content": utterance})
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
