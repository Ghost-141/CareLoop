"""Alexa+-style turn loop over discovered MCP tools.

Per turn: strip the wake word, resolve a pending confirmation, then let the
planner choose tools (up to ``max_steps``) from the account's model-visible
``tools/list``.  Destructive tools (per MCP annotations) pause for a spoken
"confirm".  The reply is built only from each result's ``speakable`` field.
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from .devices import Device, PendingAction
from .mcp_pool import MCPClientPool, Question
from .planners import Action, MockReplay, Planner, Step
from .reply_policy import DISCLAIMER, compose_reply, screen_payload, speakable, structured

Trace = Callable[[dict[str, Any]], Awaitable[None]]

_WAKE = re.compile(r"^\s*(hey\s+)?alexa[\s,.!:-]*", re.IGNORECASE)
_CONFIRM = re.compile(r"^(confirm|yes|yeah|yep|sure|ok(ay)?|please|do it|go ahead|sounds good)\b", re.IGNORECASE)
_DECLINE = re.compile(r"^(no|nope|not now|no thanks|later|maybe later)\b", re.IGNORECASE)
_MEDICAL = re.compile(r"\b(dose|dosage|medication|medicine|diagnos\w*|prescri\w*|should i take|emergency|double my)\b", re.IGNORECASE)
# A question saved for the clinician is not a request for advice: CareLoop stores it and never answers.
_CLINICIAN_QUESTION = re.compile(r"\b(question|ask)\b.*\b(doctor|clinician|nurse|care team)\b", re.IGNORECASE)
# Self-harm or a medical emergency: never routed to a tool or a model.
_CRISIS = re.compile(r"\b(kill(ing)? myself|suicid\w*|end (my|it all)|end my life|hurt(ing)? myself|self[- ]harm|"
                     r"want to die|don'?t want to (live|be here)|overdos\w*|can'?t breathe|chest pain)\b", re.IGNORECASE)
CRISIS_REPLY = ("I'm really sorry you're going through this. If you might be in danger, call your local emergency "
                "number now. In the US, you can call or text 988 for the Suicide and Crisis Lifeline. "
                "CareLoop can't help in an emergency.")
REFUSAL = "I can't give medical advice. Please contact your clinician, or emergency services in an emergency."
_CANCEL = re.compile(r"^(cancel|no|stop|never ?mind|don'?t)\b", re.IGNORECASE)


@dataclass
class Turn:
    reply: str
    tools: list[str] = field(default_factory=list)
    screen: dict[str, Any] | None = None
    needs_confirmation: bool = False
    planner: str = ""
    # (tool, structuredContent) for successful calls this turn; voice-safe by contract.
    results: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    expects_reply: bool = False  # the device should keep listening (question or confirmation)


@dataclass
class Awaiting:
    """A tool call paused on an MCP elicitation, waiting for the person's spoken answer."""
    question: Question
    task: asyncio.Task
    tool: str
    arguments: dict[str, Any]
    read_only: bool
    text: str
    steps: list
    planner: str
    attempts: int = 0


_NUMBER_WORDS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten".split())}
# Spoken words that pick an enum option when its own word isn't said (what Alexa+'s NLU would do).
_ENUM_SYNONYMS = {
    "approve": r"\b(approve|yes|yeah|yep|ok(ay)?|sure|sounds good|correct|that'?s (fine|right)|keep it|fine)\b",
    "skip": r"\b(skip|not now|later|no|nope|pass|next one)\b",
    "stop": r"\b(stop|pause|enough|that'?s all|done for now)\b",
    "change time": r"\b(change|move|reschedule|different time)\b",
    "me": r"\b(me|myself|i'?ll|i will)\b",
}
_TIME_PHRASE = re.compile(
    r"\b(?:\d{1,2}(?::\d{2})?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
    r"(?:\s*(?:a\.?m\.?|p\.?m\.?|o'?clock))?(?![\w:])", re.IGNORECASE)


def time_phrase(text: str) -> str | None:
    """The spoken time in an utterance ("9", "8 pm", "20:30"), resolved later by the server."""
    match = _TIME_PHRASE.search(text)
    return match.group(0).replace("o'clock", "").replace("oclock", "").strip() if match else None
_YES = re.compile(r"\b(yes|yeah|yep|done|did|completed|sure)\b", re.IGNORECASE)
_NO = re.compile(r"\b(no|nope|not yet|didn'?t|haven'?t)\b", re.IGNORECASE)


def tool_messages(steps) -> list[dict[str, Any]]:
    """Chat-history form of a turn's tool calls, carrying only voice-safe result fields."""
    messages: list[dict[str, Any]] = []
    for name, arguments, result, _read_only in steps:
        data = structured(result)
        visible = ({"error": result.get("text") or "unavailable"} if result.get("isError")
                   else {k: v for k, v in data.items() if k in {"status", "speakable", "refs"}})
        messages.append({"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": arguments}}]})
        messages.append({"role": "tool", "tool_name": name, "content": json.dumps(visible)})
    return messages


def parse_answer(text: str, schema: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Fill a flat MCP elicitation schema from one spoken answer: (content, re-prompt)."""
    content: dict[str, Any] = {}
    for name, prop in (schema.get("properties") or {}).items():
        if "type" not in prop and prop.get("anyOf"):  # an optional field written as anyOf[T, null]
            prop = next((p for p in prop["anyOf"] if p.get("type") != "null"), {}) | {
                k: v for k, v in prop.items() if k != "anyOf"}
        kind = prop.get("type")
        if kind in {"integer", "number"}:
            match = re.search(r"-?\d+(?:\.\d+)?", text)
            value: Any = float(match.group()) if match else None
            if value is None:
                word = next((w for w in re.findall(r"[a-z]+", text.lower()) if w in _NUMBER_WORDS), None)
                value = _NUMBER_WORDS.get(word) if word else None
            low, high = prop.get("minimum"), prop.get("maximum")
            if value is None or (low is not None and value < low) or (high is not None and value > high) \
                    or (kind == "integer" and value != int(value)):
                if name in (schema.get("required") or []):
                    span = f" from {low} to {high}" if low is not None and high is not None else ""
                    return None, f"Sorry, please say a whole number{span}."
                continue
            content[name] = int(value) if kind == "integer" else value
        elif kind == "boolean":
            if _YES.search(text):
                content[name] = True
            elif _NO.search(text):
                content[name] = False
            elif name in (schema.get("required") or []):
                return None, "Sorry, please answer yes or no."
        elif kind == "string":
            options = prop.get("enum")
            if options:
                lowered = text.lower()
                choice = next((o for o in options if re.search(rf"\b{re.escape(str(o).lower())}\b", lowered)), None)
                if choice is None:
                    choice = next((o for o in options if str(o).lower() in _ENUM_SYNONYMS
                                   and re.search(_ENUM_SYNONYMS[str(o).lower()], lowered)), None)
                if choice is None:
                    if name in (schema.get("required") or []):
                        return None, "Sorry, please choose one of: " + ", ".join(map(str, options)) + "."
                    continue
                content[name] = choice
            elif "time" in name:
                spoken = time_phrase(text)
                if spoken:
                    content[name] = spoken
            else:
                content[name] = text
    return content, None


def strip_wake_word(text: str) -> str:
    return _WAKE.sub("", text, count=1).strip()


class Orchestrator:
    def __init__(self, pool: MCPClientPool, planner: Planner | None = None, *, fallback: Planner | None = None,
                 max_steps: int = 4, trace: Trace | None = None) -> None:
        self.pool, self.planner, self.max_steps, self.trace = pool, planner or MockReplay(), max_steps, trace
        self.fallback = fallback if fallback is not None else (None if isinstance(self.planner, MockReplay) else MockReplay())
        self._inflight: dict[int, asyncio.Task] = {}

    async def respond(self, device: Device, utterance: str) -> Turn:
        text = strip_wake_word(utterance)
        if not text:
            return Turn("")
        if not self.pool.linked(device.account):
            return Turn("Please enable CareLoop for this device in the Alexa app panel first.")
        account = self.pool.accounts[device.account]
        woke = text != utterance.strip()  # "Alexa, …" starts a new request

        paused = None
        if device.awaiting is not None:
            content, _reprompt = parse_answer(text, device.awaiting.question.schema)
            if woke and not content:
                # A new "Alexa, …" request while a workflow waits: save its place, then handle the request.
                paused = await self._interrupt(device, account)
            else:
                turn = await self._answer(device, account, text)
                if turn is not None:
                    return turn
        if paused:
            turn = await self._respond_fresh(device, account, text)
            turn.reply = f"{paused} {turn.reply}".strip()
            return turn
        return await self._respond_fresh(device, account, text)

    async def _interrupt(self, device: Device, account) -> str | None:
        awaiting, device.awaiting = device.awaiting, None
        if awaiting.question.answer.done():
            return None
        awaiting.question.answer.set_result({"action": "decline"})
        outcome = await self._race(account.account_id, awaiting.task)
        while isinstance(outcome, Question):  # decline any further question from the same tool
            self._inflight.pop(id(outcome), None)
            outcome.answer.set_result({"action": "decline"})
            outcome = await self._race(account.account_id, awaiting.task)
        return speakable(outcome) if outcome and not outcome.get("isError") else None

    async def _respond_fresh(self, device: Device, account, text: str) -> Turn:
        if device.pending:
            pending, device.pending = device.pending, None
            if _CONFIRM.match(text):
                return await self._finish(device, text, [await self._call(device, account, pending.name, pending.arguments)],
                                          account.tools, "confirmation")
            if _CANCEL.match(text):
                device.remember(text, "Okay, I didn't change anything.")
                return Turn("Okay, I didn't change anything.")
        if device.offer is not None:
            offer, device.offer = device.offer, None
            if _CONFIRM.match(text):
                return await self._run_offer(device, account, text, offer)
            if _DECLINE.match(text):
                device.remember(text, "Okay.")
                return Turn("Okay.")
        if _CANCEL.fullmatch(text):
            return Turn("")
        if re.fullmatch(r"(yes|yeah|yep|no|nope|ok(ay)?|sure|thanks?( you)?)[.!]?", text, re.IGNORECASE):
            return Turn("Okay.")  # nothing is waiting on a yes or no

        # Deterministic safety responses win before any planner or model sees the request.
        if _CRISIS.search(text):
            device.remember(text, CRISIS_REPLY)
            return Turn(CRISIS_REPLY, planner="policy")
        if _MEDICAL.search(text) and not _CLINICIAN_QUESTION.search(text):
            device.remember(text, REFUSAL)
            return Turn(REFUSAL, planner="policy")
        tools, by_name = account.model_tools, {tool["name"]: tool for tool in account.model_tools}
        planner, steps, said = self.planner, [], None
        for _ in range(self.max_steps):
            try:
                action = await planner.next(text, tools, device.history, [(n, a, r) for n, a, r, _ in steps],
                                            context=device.context)
            except Exception as exc:
                if self.fallback is None or planner is self.fallback:
                    raise
                await self._log({"type": "planner_fallback", "from": planner.name, "error": type(exc).__name__})
                planner = self.fallback
                action = await planner.next(text, tools, device.history, [(n, a, r) for n, a, r, _ in steps],
                                            context=device.context)
            if not action.tool:
                said = action.say
                break
            tool = by_name.get(action.tool)
            if tool is None:
                said = "CareLoop can't do that from this account."
                break
            arguments = action.arguments or {}
            if (tool.get("annotations") or {}).get("destructiveHint"):
                prompt = self._confirmation_prompt(action.tool)
                device.pending = PendingAction(action.tool, arguments, prompt)
                device.remember(text, prompt)
                return Turn(prompt, [n for n, *_ in steps], screen_payload(self._screen(steps), device),
                            needs_confirmation=True, planner=planner.name, expects_reply=True)
            step = await self._call(device, account, action.tool, arguments)
            if isinstance(step, Question):
                return self._ask(device, Awaiting(step, self._inflight.pop(id(step)), action.tool, arguments,
                                                  bool((tool.get("annotations") or {}).get("readOnlyHint")),
                                                  text, steps, planner.name), remember=text)
            steps.append(step)
            if steps[-1][2].get("isError"):
                break
        if not steps:
            reply = said or "Sorry, I can't help with that in CareLoop yet."
            device.remember(text, reply)
            return Turn(reply, planner=planner.name)
        return await self._finish(device, text, steps, account.tools, planner.name)

    async def _run_offer(self, device: Device, account, text: str, offer: dict[str, Any]) -> Turn:
        """The person said yes to the server's offer: call exactly that tool."""
        tool = next((t for t in account.model_tools if t["name"] == offer["tool"]), None)
        if tool is None or (tool.get("annotations") or {}).get("destructiveHint"):
            return Turn("Sorry, I can't do that from here.")
        step = await self._call(device, account, offer["tool"], offer["arguments"])
        if isinstance(step, Question):
            return self._ask(device, Awaiting(step, self._inflight.pop(id(step)), offer["tool"], offer["arguments"],
                                              bool((tool.get("annotations") or {}).get("readOnlyHint")),
                                              text, [], "offer"), remember=text)
        turn = await self._finish(device, text, [step], account.tools, "offer")
        if offer.get("retry_text") and not step[2].get("isError"):
            # e.g. data-use consent accepted: now do what the person originally asked.
            follow = await self._respond_fresh(device, account, offer["retry_text"])
            follow.reply = f"{turn.reply} {follow.reply}".strip()
            follow.tools = turn.tools + follow.tools
            return follow
        return turn

    async def _call(self, device: Device, account, name: str, arguments: dict[str, Any]):
        """Call a tool; if the server asks a question first, return that Question instead."""
        tool = next((t for t in account.tools if t["name"] == name), {})
        task = asyncio.create_task(self.pool.call_tool(account.account_id, name, arguments))
        outcome = await self._race(account.account_id, task)
        if isinstance(outcome, Question):
            self._inflight[id(outcome)] = task
            return outcome
        read_only = bool((tool.get("annotations") or {}).get("readOnlyHint"))
        return name, arguments, outcome, read_only

    async def _race(self, account_id: str, task: asyncio.Task):
        """Wait for the tool result, or for an elicitation the server sends while it runs."""
        queue = getattr(self.pool, "questions", {}).get(account_id)
        if queue is None:
            return await task
        getter = asyncio.create_task(queue.get())
        done, _ = await asyncio.wait({task, getter}, return_when=asyncio.FIRST_COMPLETED)
        if task in done:
            if getter in done:
                queue.put_nowait(getter.result())
            else:
                getter.cancel()
            return task.result()
        return getter.result()

    def _ask(self, device: Device, awaiting: Awaiting, *, remember: str, prompt: str | None = None) -> Turn:
        # The question/answer exchange belongs to the server's tool, not the model's
        # conversation: history records only the original request and its outcome, so a
        # model never learns to ask the tool's question itself.
        device.awaiting = awaiting
        spoken = prompt or awaiting.question.message
        return Turn(spoken, [n for n, *_ in awaiting.steps] + [awaiting.tool], planner=awaiting.planner, expects_reply=True)

    async def _answer(self, device: Device, account, text: str) -> Turn | None:
        """Resolve the pending elicitation with this utterance and finish the paused tool call."""
        awaiting = device.awaiting
        if awaiting.question.answer.done():  # timed out or cancelled server-side
            device.awaiting = None
            return None
        if _CANCEL.match(text):
            awaiting.question.answer.set_result({"action": "decline"})
        else:
            content, reprompt = parse_answer(text, awaiting.question.schema)
            if reprompt:
                awaiting.attempts += 1
                if awaiting.attempts < 2:
                    return self._ask(device, awaiting, remember=text, prompt=reprompt)
                awaiting.question.answer.set_result({"action": "cancel"})
            else:
                awaiting.question.answer.set_result({"action": "accept", "content": content})
        device.awaiting = None
        outcome = await self._race(account.account_id, awaiting.task)
        if isinstance(outcome, Question):  # a further question from the same tool
            self._inflight.pop(id(outcome), None)
            awaiting.question, awaiting.attempts = outcome, 0
            return self._ask(device, awaiting, remember=text)
        steps = awaiting.steps + [(awaiting.tool, awaiting.arguments, outcome, awaiting.read_only)]
        return await self._finish(device, awaiting.text, steps, account.tools, awaiting.planner)

    async def _finish(self, device: Device, text: str, steps, tools: list[dict[str, Any]], planner: str) -> Turn:
        reply = compose_reply(self._screen(steps), disclaimer=not device.disclaimed)
        device.disclaimed = device.disclaimed or DISCLAIMER in reply or "not medical advice" in reply.lower()
        device.remember(text, reply, tool_messages(steps))
        screen = screen_payload(self._screen(steps), device)
        if screen:
            # MCP Apps: the host renders the view declared on the *tool definition*.
            meta_uri = (((next((t for t in tools if t["name"] == screen["tool"]), {}).get("_meta") or {})
                         .get("ui") or {}).get("resourceUri"))
            screen["resource_uri"] = meta_uri or screen["resource_uri"]
        results = [(name, structured(result)) for name, _args, result, _ in steps if not result.get("isError")]
        self._remember_context(device, results)
        offer = next((data.get("next_step") for _name, data in reversed(results) if data.get("next_step")), None)
        device.offer = ({"tool": offer["tool"], "arguments": offer.get("arguments") or {},
                         "retry_text": text if offer.get("retry") else None} if offer else None)
        return Turn(reply, [name for name, *_ in steps], screen, planner=planner, results=results,
                    expects_reply=device.offer is not None)

    @staticmethod
    def _remember_context(device: Device, results: list[tuple[str, dict[str, Any]]]) -> None:
        """Keep the last single task and person mentioned, so "it", "that one" and "him" resolve."""
        for _name, data in results:
            refs = data.get("refs") or []
            tasks = [r for r in refs if r.get("kind") == "task" and r.get("status") == "active"]
            if len(tasks) == 1:
                task = tasks[0]
                device.context["task"] = {"id": task["id"], "title": task.get("title"), "times": task.get("times", [])}
                if task.get("assignee_id"):
                    device.context["person"] = {"id": task["assignee_id"], "name": task.get("assignee")}
            people = [r for r in refs if r.get("kind") == "caregiver_grant" and r.get("status") == "active"]
            if len(people) == 1:
                device.context["person"] = {"id": people[0]["id"], "name": people[0].get("name")}

    @staticmethod
    def _screen(steps) -> list[tuple[str, dict[str, Any], bool]]:
        return [(name, result, read_only) for name, _args, result, read_only in steps]

    @staticmethod
    def _confirmation_prompt(name: str) -> str:
        what = {"revoke_caregiver": "remove this caregiver's CareLoop access",
                "delete_care_record": "permanently delete this CareLoop record"}.get(name, "make this change")
        return f"This will {what}. Say confirm to continue, or cancel."

    async def _log(self, entry: dict[str, Any]) -> None:
        if self.trace:
            await self.trace(entry)
