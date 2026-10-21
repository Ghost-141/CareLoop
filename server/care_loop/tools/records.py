"""CareLoop MCP tools in the Alexa+ voice-safe result shape.

Every tool returns a typed ``VoiceResult``:

* ``speakable`` is safe to read aloud on a shared speaker: counts and statuses
  only, never plan text, observation values, alert content, or source excerpts;
* ``refs`` carry opaque record identifiers plus non-clinical labels so a client
  can act on a specific item ("approve the first draft") without seeing it;
* ``ui://careloop/<view>`` is declared on each tool definition as
  ``_meta.ui.resourceUri`` for MCP Apps hosts.  Private detail reaches the
  view only through the app-only ``get_private_view`` tool.

Failures raise ``ToolError`` so the host sees ``isError`` and never reports a
failed action as done.  The error text is generic and contains no record data.
"""
from __future__ import annotations

import inspect
import re
import uuid
from datetime import UTC, datetime, time
from functools import wraps
from typing import Any, Literal, NotRequired, TypedDict

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field, create_model

from ..core import CRISIS, CRISIS_REPLY, AccessDenied, ConsentRequired, NoCareAccess, PastExpiry
from ..teach_back import in_period, medicine_name, period_named


Surface = Literal["glance", "private_screen"]
_LAST_DAYS = re.compile(r"last_(?P<days>[1-9][0-9]*)_days$")


class Ref(TypedDict):
    """An opaque record handle. ``label`` is positional, never record content."""
    id: str
    kind: str
    label: str
    status: NotRequired[str]
    scopes: NotRequired[list[str]]
    expires_at: NotRequired[int | None]
    name: NotRequired[str]  # the patient's own short name for a family member
    title: NotRequired[str]  # a task's spoken name (the patient can edit it)
    assignee_id: NotRequired[str]  # the caregiver_grant ref of the person doing the task
    times: NotRequired[list[str]]  # a task's scheduled local times, e.g. "20:00"
    assignee: NotRequired[str]


class Reminder(TypedDict):
    """A reminder Alexa+ should create with its own native feature. CareLoop never schedules it."""
    task_id: str
    label: str
    times: list[str]
    to: str  # "patient", or the family member's name


class NextStep(TypedDict):
    """An offer the host may make: if the person says yes, call exactly this tool. Never destructive."""
    say: str
    tool: str
    arguments: dict[str, Any]
    retry: NotRequired[bool]  # after the offered tool succeeds, repeat the person's original request


class VoiceResult(TypedDict):
    status: Literal["ok"]
    speakable: str
    surface: Surface
    view: str
    refs: list[Ref]
    reminders: NotRequired[list[Reminder]]
    next_step: NotRequired[NextStep]


def _view_uri(view: str) -> str:
    return f"ui://careloop/{view}"


def _result(speakable: str, *, view: str, refs: list[Ref] | None = None, surface: Surface = "private_screen",
            reminders: list[dict[str, Any]] | None = None, next_step: NextStep | None = None) -> VoiceResult:
    if next_step:
        speakable = f"{speakable} {next_step['say']}"
    result: VoiceResult = {"status": "ok", "speakable": speakable, "surface": surface, "view": _view_uri(view), "refs": refs or []}
    if next_step:
        result["next_step"] = next_step
    if reminders:
        result["reminders"] = [{"task_id": r["task_id"], "label": r["label"], "times": r["times"], "to": r["for"]}
                               for r in reminders]
    return result


def _join(parts: list[str]) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def _say_time(value: str) -> str:
    """ "19:00" → "7 PM", "08:30" → "8:30 AM", "12:00" → "noon" — what a speaker should say."""
    try:
        hour, minute = (int(part) for part in value.split(":"))
    except ValueError:
        return value
    if (hour, minute) == (12, 0):
        return "noon"
    if (hour, minute) == (0, 0):
        return "midnight"
    clock = f"{hour % 12 or 12}" + (f":{minute:02d}" if minute else "")
    return f"{clock} {'AM' if hour < 12 else 'PM'}"


def _say_times(times: list[str]) -> str:
    return _join([_say_time(t) for t in times])


# Meal wording the prescription itself uses. It is spoken as written, never inferred from a time.
_MEAL = re.compile(r"\b(?:before|after|with)\s+(?:breakfast|lunch|dinner|supper|meals?|food)\b|\bon an empty stomach\b"
                   r"|\bat bedtime\b", re.IGNORECASE)
_PERIOD_PHRASE = {"morning": "in the morning", "afternoon": "in the afternoon", "evening": "in the evening", "night": "at night"}


def _medicines_speakable(items: list[dict[str, Any]], when: str | None) -> str:
    """The patient's own approved medicines, each with its time, the plan's meal wording and its source line."""
    period = period_named(when) if when else None
    parts = []
    for item in items:
        if item.get("item_kind") != "medication_task" or item.get("status", "active") != "active":
            continue
        times = list(item.get("times") or [])
        if period:
            times = [t for t in times if in_period(t, period)]
            if not times:
                continue
        part = f"{medicine_name(item)} at {_say_times(times)}" if times else f"{medicine_name(item)} as needed"
        if meal := _MEAL.search(item.get("text") or ""):
            part += f", {meal.group(0).lower()}"
        line = re.search(r"L(\d+)$", str(((item.get("source") or [{}])[0]).get("id") or ""))
        if line:
            part += f", from line {line.group(1)}"
        parts.append((min(times) if times else "99", part))  # in time order; "as needed" last
    parts = [part for _, part in sorted(parts)]
    if not parts:
        return (f"No medicine in your approved plan is due {_PERIOD_PHRASE[period]}." if period
                else "Your approved plan has no medicines yet.")
    lead = f"{_PERIOD_PHRASE[period][0].upper()}{_PERIOD_PHRASE[period][1:]}" if period else "Your medicines"
    return f"{lead}: {'; '.join(parts)}."


DATA_USE_PROMPT = ("Before I save anything: CareLoop keeps your care plan, your check-ins, and who you share them "
                   "with, so you and the people you choose can coordinate your care. It's not medical advice, and "
                   "you can export or delete your data anytime. The privacy policy is in the CareLoop app. "
                   "Is that okay?")


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


NO_ACCESS = ("You don't have access to the patient's CareLoop right now. "
             "If they invited you, open the invitation link in your Alexa app.")
PERMISSION_WORDS = {"read_tasks": "see your tasks", "read_observations": "see your check-ins",
                    "write_observations": "record check-ins for you", "receive_alerts": "get update alerts",
                    "acknowledge_alerts": "mark updates as seen", "upload_documents": "share documents with you",
                    "perform_tasks": "be given tasks to do"}


class ConfirmInvite(BaseModel):
    """Elicitation schema: the patient confirms exactly what a family member will be able to do."""
    confirm: bool = Field(description="yes if these permissions are right")


def _explain(exc: Exception, message: str) -> str:
    """Generic by default; specific only where the reason reveals nothing private."""
    if isinstance(exc, ToolError) and exc.__cause__ is None:
        return str(exc)  # a message the tool chose deliberately
    cause = exc.__cause__ if isinstance(exc, ToolError) else exc
    if isinstance(cause, NoCareAccess):
        return NO_ACCESS
    if isinstance(cause, PastExpiry):
        return "That expiry date is in the past. Say how many days the access should last."
    return message


def _consent_prompt() -> VoiceResult:
    """Shown instead of a result until the patient accepts data use; "yes" accepts and repeats the request."""
    return _result(DATA_USE_PROMPT.removesuffix(" Is that okay?"), view="care-circle",
                   next_step={"say": "Is that okay?", "tool": "accept_data_use", "arguments": {}, "retry": True})


def _safe_tool(message: str):
    """Map anticipated authorization/validation failures to one generic ToolError.

    Only domain failures are converted.  Programming errors (``TypeError``,
    ``AttributeError``…) still surface as tool errors through the SDK, but are
    not silently relabelled as an expected refusal.
    """
    def decorate(function):
        if inspect.iscoroutinefunction(function):
            @wraps(function)
            async def safe_async(*args, **kwargs):
                try:
                    return await function(*args, **kwargs)
                except ConsentRequired:
                    return _consent_prompt()
                except (ToolError, AccessDenied, ValueError, OverflowError) as exc:
                    raise ToolError(_explain(exc, message)) from exc
            return safe_async

        @wraps(function)
        def safe(*args, **kwargs):
            try:
                return function(*args, **kwargs)
            except ConsentRequired:
                return _consent_prompt()
            except (ToolError, AccessDenied, ValueError, OverflowError) as exc:
                raise ToolError(_explain(exc, message)) from exc
        return safe
    return decorate


class PainCheckIn(BaseModel):
    """Elicitation schema for the daily check-in: one validated, uninterpreted value."""
    pain_score: int = Field(ge=0, le=10, description="Pain score today, a whole number from 0 (none) to 10 (worst)")


CHECKIN_QUESTION = "On a scale from 0 to 10, what's your pain score today?"


class TaskDone(BaseModel):
    """Elicitation schema for one check-in task question."""
    done: bool = Field(description="yes if the task was done today")


class TeachBackAnswer(BaseModel):
    """Elicitation schema for one teach-back question: the person's own words. CareLoop checks them in code."""
    answer: str = Field(description="What the person said, in their own words")


_ABOUT_VALUES = re.compile(r"\b(pain|scores?|check-?ins?|symptoms?|how (is|was|are|has) (she|he|they|maya))\b", re.IGNORECASE)
TEACH_BACK_ATTEMPTS = 2  # a second try, then the plan is read back
TEACH_BACK_MISS_LIMIT = 3  # misses in a row before the rest is left for the clinician


def _review_offer(service, identity) -> NextStep | None:
    voice, _screen = service.voice_reviewable(identity)
    if not voice:
        return None
    return {"say": "Want to go through them now?", "tool": "review_plan_by_voice", "arguments": {}}


def _assign_offer(service, identity) -> NextStep | None:
    found = service.assign_offer(identity)
    if not found:
        return None
    task, grant = found
    who = grant.get("display_name") or "your family member"
    return {"say": f"Want {who} to handle {task.get('label') or 'that task'}?", "tool": "assign_task",
            "arguments": {"task": task["id"], "assignee": grant["id"]}}


def _describe(service, item: dict[str, Any]) -> str:
    if item["type"] == "PLAN_RULE":
        spec = service._rule_spec(item) or {}
        if spec:
            return (f"Alert rule: contact your clinic when your pain score is {spec['threshold']} or higher "
                    f"for {spec['consecutive_days']} days in a row")
        return "Follow-up rule"
    # Document lines end in their own full stop; the prompt adds its own punctuation.
    text = (item.get("text") or item.get("label") or "Care item").rstrip(" .")
    text = re.sub(r"^\s*(?:\d{1,2}|[a-z])[.)]\s+", "", text)  # a document's list numbering is not part of the instruction
    if item["type"] == "PLAN_TASK" and item.get("times"):
        text += f", at {_say_times(item['times'])}"
    return text


def _review_schema(is_task: bool, helpers: list[str]):
    actions = ("approve", "change time", "skip", "stop") if is_task else ("approve", "skip", "stop")
    fields: dict[str, Any] = {"action": (Literal[actions] | None, Field(None, description="What to do with this item"))}
    if is_task:
        fields["new_time"] = (str | None, Field(None, description="A new time, as spoken, e.g. '8 pm'"))
        if helpers:
            fields["who"] = (Literal[tuple(["me", *helpers])] | None, Field(None, description="Who will do it"))
    return create_model("ReviewItem" + ("Task" if is_task else ""), **fields)


def _date_bound(value: int | str, *, end_of_day: bool) -> int:
    """Normalize an epoch or ISO-8601 date/time to a UTC epoch bound."""
    if isinstance(value, bool):
        raise ValueError("date must be an epoch or ISO-8601 value")
    if isinstance(value, int):
        if value < 0:
            raise ValueError("date must not be negative")
        return value
    if not isinstance(value, str) or not value.strip():
        raise ValueError("date must be an epoch or ISO-8601 value")
    raw = value.strip()
    try:
        # A date represents its full UTC calendar day, which makes a handoff
        # such as 2026-10-01 through 2026-10-07 inclusive.
        if len(raw) == 10:
            day = datetime.strptime(raw, "%Y-%m-%d").date()
            return int(datetime.combine(day, time.max if end_of_day else time.min, UTC).timestamp())
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("date must be an epoch or ISO-8601 value") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.astimezone(UTC).timestamp())


def _date_range(
    from_date: int | str | None, to_date: int | str | None, *, now: int, required: bool
) -> tuple[int | None, int | None]:
    """Resolve explicit ISO/epoch bounds or one supported relative range."""
    if isinstance(from_date, str):
        match = _LAST_DAYS.fullmatch(from_date.strip())
        if match:
            if to_date is not None:
                raise ValueError("a relative range cannot include to_date")
            return now - int(match.group("days")) * 86_400, now
    if required and (from_date is None or to_date is None):
        raise ValueError("from_date and to_date are required")
    start = None if from_date is None else _date_bound(from_date, end_of_day=False)
    end = None if to_date is None else _date_bound(to_date, end_of_day=True)
    if start is not None and end is not None and end < start:
        raise ValueError("invalid date range")
    return start, end


def _handoff_dates(from_date: int | str | None, to_date: int | str | None, *, now: int) -> tuple[int, int]:
    start, end = _date_range(from_date, to_date, now=now, required=True)
    assert start is not None and end is not None
    return start, end


def _plan_refs(items: list[dict[str, Any]]) -> list[Ref]:
    refs: list[Ref] = []
    counters: dict[str, int] = {}
    for item in items:
        kind = {"PLAN_RULE": "rule", "PLAN_NOTE": "note"}.get(item["type"], "task")
        status = item.get("status", "active")
        key = f"{status} {kind}"
        counters[key] = counters.get(key, 0) + 1
        ref: Ref = {"id": item["id"], "kind": kind, "status": status, "label": f"{key} {counters[key]}"}
        if item.get("times"):
            ref["times"] = list(item["times"])
        if item.get("assignee_name"):
            ref["assignee"] = item["assignee_name"]
        if item.get("assignee_grant_id"):
            ref["assignee_id"] = item["assignee_grant_id"]
        # The spoken name is shared only once the patient has approved the task (and its name).
        if kind == "task" and item.get("label") and status == "active":
            ref["title"] = item["label"]
        refs.append(ref)
    return refs


_RECORD_NOUNS = {"OBSERVATION": "pain check-in", "PLAN_TASK": "care task", "PLAN_RULE": "follow-up rule", "CONSENT": "caregiver access",
                 "ALERT": "update", "DOCUMENT": "document", "TASK_EVENT": "task update", "QUESTION": "clinician question",
                 "HANDOFF": "visit handoff", "PLAN_NOTE": "plan note"}


_RECORD_ALIASES = {**{noun: kind for kind, noun in _RECORD_NOUNS.items()},
                   "pain": "OBSERVATION", "pain score": "OBSERVATION", "pain level": "OBSERVATION", "pain observation": "OBSERVATION",
                   "check-in": "OBSERVATION", "checkin": "OBSERVATION", "task": "PLAN_TASK", "rule": "PLAN_RULE",
                   "caregiver": "CONSENT", "question": "QUESTION", "handoff": "HANDOFF"}


def _record_type(value: str | None) -> str | None:
    """Accept a record type as the model may phrase it ("pain check-in") or as stored ("OBSERVATION")."""
    if value is None or not str(value).strip():
        return None
    cleaned = " ".join(str(value).replace("_", " ").split()).casefold()
    return _RECORD_ALIASES.get(cleaned) or str(value).strip().upper().replace(" ", "_")


def _resolve_record(deps, patient, value: str) -> str:
    """A record id, or the label list_care_records gave it ("latest pain check-in"), as the record id."""
    records = deps.service.list_records(patient)
    if any(record["id"] == value for record in records):
        return value
    wanted = " ".join(str(value).split()).casefold()
    matches = [ref["id"] for ref in _record_refs(records) if ref["label"].casefold() == wanted]
    if len(matches) != 1:
        raise ValueError("record label matches no one record")
    return matches[0]


def _record_refs(records: list[dict[str, Any]]) -> list[Ref]:
    """Opaque ids labelled by kind and position only; labels never carry values or dates."""
    totals: dict[str, int] = {}
    for record in records:
        totals[record["type"]] = totals.get(record["type"], 0) + 1
    seen: dict[str, int] = {}
    refs: list[Ref] = []
    for record in records:
        kind = record["type"]
        seen[kind] = seen.get(kind, 0) + 1
        noun = _RECORD_NOUNS.get(kind, "record")
        label = f"latest {noun}" if seen[kind] == totals[kind] else f"{noun} {seen[kind]}"
        refs.append({"id": record["id"], "kind": kind.lower(), "label": label})
    return refs


def _grant_refs(grants: list[dict[str, Any]]) -> list[Ref]:
    refs: list[Ref] = []
    for index, grant in enumerate(grants, start=1):
        ref: Ref = {"id": grant["id"], "kind": "caregiver_grant", "status": grant.get("status", "active"),
                    "label": f"caregiver access {index}", "scopes": list(grant.get("scopes", [])),
                    "expires_at": grant.get("expires_at")}
        if grant.get("display_name"):
            ref["name"] = grant["display_name"]
        refs.append(ref)
    return refs


def _patient(deps, ctx, *, consent: bool = True):
    try:
        identity = deps.identity(ctx)
    except AccessDenied as exc:
        raise ToolError("Not authorized for this CareLoop patient.") from exc
    if consent:
        deps.service.require_data_use_consent(identity)
    return identity


_READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
_WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
_IDEMPOTENT_WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
_DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)


_TITLES: dict[str, str] = {
    "import_care_plan_text": "Import care plan",
    "approve_plan_item": "Approve plan item",
    "list_care_tasks": "List care tasks",
    "record_task_completion": "Record task completion",
    "get_care_plan_source": "Open plan source",
    "get_intake_status": "Check document intake",
    "review_plan_item": "Review plan item",
    "accept_data_use": "Accept data use",
    "set_my_details": "Set my details",
    "review_plan_by_voice": "Review plan by voice",
    "update_task_time": "Change task time",
    "assign_task": "Assign task to family",
    "list_my_assigned_tasks": "List my assigned tasks",
    "add_question_for_clinician": "Add question for clinician",
    "who_accessed_my_care_data": "Who accessed my care data",
    "list_care_circle": "List care circle",
    "invite_caregiver": "Invite caregiver",
    "accept_caregiver_invitation": "Accept caregiver invitation",
    "revoke_caregiver": "Revoke caregiver access",
    "list_generic_notifications": "List care updates",
    "acknowledge_alert": "Acknowledge alert",
    "start_daily_checkin": "Start daily check-in",
    "record_pain_observation": "Record pain level",
    "correct_pain_observation": "Correct pain level",
    "list_care_records": "List care records",
    "search_care_history": "Search care history",
    "create_visit_handoff": "Create visit handoff",
    "export_care_data": "Export care data",
    "delete_care_record": "Delete care record",
    "get_private_view": "Get private view",
    "get_suggestions": "What needs my attention",
    "start_teach_back": "Check my understanding",
}


def _ui(view: str, *, app_only: bool = False) -> dict[str, Any]:
    if app_only:
        # MCP Apps visibility: callable by a rendered view, hidden from the model.
        return {"ui": {"visibility": ["app"]}}
    return {"ui": {"resourceUri": _view_uri(view)}}


def register(mcp: MCPServer, deps) -> None:
    def tool(name: str, view: str, annotations: ToolAnnotations, *, app_only: bool = False):
        return mcp.tool(name=name, title=_TITLES[name], annotations=annotations, meta=_ui(view, app_only=app_only))

    # ---- plan intake and review -------------------------------------------------
    @tool("import_care_plan_text", "plan-review", _WRITE)
    @_safe_tool("Care plan import is unavailable.")
    def import_care_plan_text(title: str, text: str, ctx: Context) -> VoiceResult:
        """Import plan text the person actually provided (pasted or dictated "TASK: …" lines).

        Never invent or summarise plan text. If someone says they got a plan or prescription
        without giving its text, don't call this: ask them to share the document in the Alexa
        app, then use get_intake_status. Extracted directives become drafts that still need
        explicit patient approval.
        """
        from ..intake import extract_text_fixture
        try:
            found = extract_text_fixture(text).drafts
        except ValueError:
            found = []
        if not found:
            raise ToolError("I couldn't find plan instructions in that. Share the document in the "
                            "Alexa app, and I'll read it for you.")
        intake = deps.service.intake_text_document(_patient(deps, ctx), title, text)
        drafts = intake["drafts"]
        reviewable = sum(1 for draft in drafts if draft.get("status") == "draft")
        speakable = f"Imported {_plural(len(drafts), 'plan item')} for your review."
        if intake["manual_review_required"]:
            speakable += " Some instructions need manual review before they can be approved."
        elif reviewable:
            speakable += " You can approve them on your screen, or by voice."
        identity = _patient(deps, ctx)
        return _result(speakable, view="plan-review", refs=_plan_refs(drafts),
                       next_step=_review_offer(deps.service, identity))

    @tool("approve_plan_item", "plan-review", _IDEMPOTENT_WRITE)
    @_safe_tool("That item needs your review on screen before it can be approved.")
    def approve_plan_item(record_id: str, ctx: Context) -> VoiceResult:
        """Patient-confirm one source-cited draft (a ref id from list/import) so it becomes active.

        Medicine items and items flagged for review can only be approved on the patient's screen.
        """
        item = deps.service.approve_plan_item(_patient(deps, ctx), record_id)
        reminders = deps.service.reminder_suggestions([item])
        kind = {"PLAN_RULE": "rule", "PLAN_NOTE": "note"}.get(item["type"], "task")
        identity = _patient(deps, ctx)
        offer = _assign_offer(deps.service, identity) if not deps.service.voice_reviewable(identity)[0] else None
        return _result(f"Plan {kind} approved and now active.", view="plan-review", refs=_plan_refs([item]),
                       reminders=reminders, next_step=offer)

    @tool("list_care_tasks", "tasks", _READ)
    @_safe_tool("Care tasks are unavailable.")
    def list_care_tasks(ctx: Context, medicines: bool = False, when: str | None = None) -> VoiceResult:
        """List counts and ref ids of the person's plan tasks/rules.

        Patients also see their own unapproved drafts; caregivers never receive
        draft instructions.  Task wording is shown only in the private view.

        When the patient asks which medicines they take ("what medicine do I take before breakfast?",
        "when do I take omeprazole?"), pass ``medicines=true`` and, if they name a part of the day or a
        meal, ``when`` ("breakfast", "dinner", "morning", "bedtime"). The patient then hears each approved
        medicine with its time and source line. A family member still hears only counts.
        """
        identity = _patient(deps, ctx)
        items = deps.service.list_care_tasks(identity)
        if (medicines or when) and identity.role == "patient":
            return _result(_medicines_speakable(items, when), view="tasks", refs=_plan_refs(items))
        tasks = [i for i in items if i["type"] == "PLAN_TASK" and i.get("status", "active") == "active"]
        rules = [i for i in items if i["type"] == "PLAN_RULE" and i.get("status", "active") == "active"]
        drafts = [i for i in items if i.get("status", "active") in {"draft", "pending_review", "needs_review"}]
        if not items:
            speakable = "You have no CareLoop plan items yet."
        else:
            speakable = f"You have {_plural(len(tasks), 'active task')} and {_plural(len(rules), 'active follow-up rule')}."
            if drafts:
                speakable += f" {_plural(len(drafts), 'draft')} {'needs' if len(drafts) == 1 else 'need'} your review."
        return _result(speakable, view="tasks", refs=_plan_refs(items))

    @tool("record_task_completion", "tasks", _WRITE)
    @_safe_tool("That task can't be marked complete.")
    def record_task_completion(task_id: str, ctx: Context, completed_at: int | str | None = None) -> VoiceResult:
        """Record completion of one active task (ref id). ``completed_at`` accepts epoch or ISO-8601.

        A family member can complete only tasks assigned to them (see ``list_my_assigned_tasks``).
        """
        identity = _patient(deps, ctx)
        when = None if completed_at is None else _date_bound(completed_at, end_of_day=False)
        event = deps.service.record_task_completion(identity, task_id, when)
        speakable = ("Thanks. I've recorded that you did it." if identity.role == "caregiver"
                     else "Task completion recorded.")
        return _result(speakable, view="tasks", surface="glance" if identity.role == "caregiver" else "private_screen",
                       refs=[{"id": event["id"], "kind": "task_event", "label": "completion"}])

    @tool("get_care_plan_source", "plan-source", _READ)
    @_safe_tool("Care plan source is unavailable.")
    def get_care_plan_source(source_id: str, ctx: Context) -> VoiceResult:
        """Open a reviewed, task-linked source excerpt on the private screen."""
        deps.service.source_excerpt(_patient(deps, ctx), source_id)
        return _result("The source excerpt is on your private screen.", view="plan-source",
                       refs=[{"id": source_id, "kind": "source", "label": "plan source"}])

    @tool("get_intake_status", "plan-review", _READ)
    @_safe_tool("Document status is unavailable.")
    def get_intake_status(ctx: Context) -> VoiceResult:
        """Status of the most recently uploaded document: still reading, ready for review (with counts), or unreadable.

        Documents are uploaded in the CareLoop private view or the Alexa app, never by voice.
        """
        identity = _patient(deps, ctx)
        jobs = deps.service.intake_jobs(identity)
        if not jobs:
            return _result("There are no uploaded documents.", view="plan-review")
        job = jobs[0]
        refs: list[Ref] = [{"id": job["id"], "kind": "document_job", "status": job["status"], "label": "latest document"}]
        if job["status"] == "processing":
            return _result("I'm still reading the document. I'll have it ready in a moment.", view="plan-review", refs=refs)
        if job["status"] == "failed":
            return _result("I couldn't read that document. Try a typed PDF, or a clearer photo.", view="plan-review", refs=refs)
        counts = job.get("counts", {})
        total, flagged = counts.get("items", 0), counts.get("needs_review", 0)
        if identity.role == "caregiver":
            return _result(f"The document you shared is ready. The patient will review {_plural(total, 'item')}.",
                           view="plan-review", surface="glance", refs=refs)
        pending = [i for i in deps.service.list_care_tasks(identity)
                   if i.get("intake_job_id") == job["id"] and i.get("status") in {"draft", "needs_review"}]
        speakable = f"Your document is ready. {_plural(len(pending), 'item')} {'needs' if len(pending) == 1 else 'need'} your approval"
        speakable += f", and {flagged} {'is' if flagged == 1 else 'are'} flagged for a closer look." if flagged else "."
        if counts.get("medication_items"):
            speakable += " Medicine items are approved on your screen."
        return _result(speakable, view="plan-review", refs=refs + _plan_refs(pending),
                       next_step=_review_offer(deps.service, identity))

    @tool("review_plan_item", "", _IDEMPOTENT_WRITE, app_only=True)
    @_safe_tool("That item couldn't be updated. Check each flag and try again.")
    def review_plan_item(record_id: str, action: Literal["approve", "reject"], ctx: Context, confirmed: bool = False,
                         label: str | None = None, times: list[str] | None = None) -> VoiceResult:
        """App-only (the patient's review screen): approve, edit-and-approve, or reject one draft.

        ``confirmed`` = the patient checked every flag shown beside the item. Only the spoken
        label and suggested times may be edited; the cited instruction never changes.
        """
        identity = _patient(deps, ctx)
        if action == "reject":
            deps.service.reject_plan_item(identity, record_id)
            return _result("Item removed. It won't be added to your plan.", view="plan-review")
        edits = {k: v for k, v in {"label": label, "times": times}.items() if v is not None}
        item = deps.service.approve_plan_item(identity, record_id, on_screen=True, confirmed=confirmed, edits=edits)
        return _result("Approved. It's now part of your plan.", view="plan-review", refs=_plan_refs([item]),
                       reminders=deps.service.reminder_suggestions([item]))

    # ---- data-use consent and the patient's own details -------------------------------
    @tool("accept_data_use", "care-circle", _IDEMPOTENT_WRITE)
    @_safe_tool("That couldn't be saved.")
    def accept_data_use(ctx: Context) -> VoiceResult:
        """Patient accepts CareLoop's data use (the disclosure CareLoop read to them). Call only after a clear yes."""
        identity = _patient(deps, ctx, consent=False)
        deps.service.accept_data_use(identity)
        return _result("Thanks, you're all set.", view="care-circle")

    @tool("get_suggestions", "tasks", _READ)
    @_safe_tool("Suggestions are unavailable.")
    def get_suggestions(ctx: Context) -> VoiceResult:
        """PATIENT ONLY: things worth raising right now, drawn from the patient's own records.

        Call it for "anything I should know", "anything coming up", "what's next" or "what needs my attention".
        It is not the task list: "what do I need to do today" is list_care_tasks. Each suggestion is computed by code from approved records: a visit coming up, a missed task, no
        check-in today, plan items waiting for review, part of the plan never checked back. Speak only what this returns, never add a suggestion of
        your own, and when nothing applies say so. If a suggestion carries a question, ask it and run that tool on yes.
        """
        identity = _patient(deps, ctx)
        if identity.role != "patient":
            raise AccessDenied("Suggestions are for the patient")
        if not deps.service.suggestions_enabled(identity.patient):
            return _result("Suggestions are turned off. Say turn suggestions on whenever you want them back.", view="tasks")
        items = deps.service.suggestions(identity)
        if not items:
            return _result("Nothing needs your attention right now.", view="tasks")
        lead = f"You have {len(items)} things worth a look. " if len(items) > 1 else ""
        # One question at most: the first suggestion that has one. It is spoken last, right after its own line.
        offered = next((i for i in items if i["offer"]), None)
        spoken = [i for i in items if i is not offered] + ([offered] if offered else [])
        return _result(lead + " ".join(i["say"] for i in spoken), view="tasks",
                       refs=[{"id": i["id"], "kind": "suggestion", "label": f"suggestion {n}"} for n, i in enumerate(items, start=1)],
                       next_step=offered["offer"] if offered else None)

    @tool("set_my_details", "care-circle", _IDEMPOTENT_WRITE)
    @_safe_tool("Those details couldn't be saved.")
    def set_my_details(ctx: Context, name: str | None = None, timezone: str | None = None,
                       suggestions: bool | None = None) -> VoiceResult:
        """Patient sets the name family members hear ("Maya"), their IANA time zone ("Asia/Dhaka"), and whether
        suggestions are on ("turn suggestions off" sets suggestions to false)."""
        profile = deps.service.update_profile(_patient(deps, ctx), name=name, timezone=timezone, suggestions=suggestions)
        parts = []
        if name:
            parts.append(f"I'll call you {profile['display_name']}")
        if timezone:
            parts.append(f"times now follow {profile['timezone'].replace('_', ' ')}")
        if suggestions is not None:
            parts.append("suggestions are " + ("on" if profile["suggestions"] else "off"))
        return _result(("Done. " + " and ".join(parts) + ".") if parts else "Nothing changed.", view="care-circle")

    # ---- guided, resumable voice review ---------------------------------------------
    @tool("review_plan_by_voice", "plan-review", _WRITE)
    @_safe_tool("Voice review isn't available here. Review the items on your screen.")
    async def review_plan_by_voice(ctx: Context) -> VoiceResult:
        """Walk the patient through their draft plan items one at a time by voice, asking about each.

        Starts a review, or continues a paused one ("continue my review"). For each item the
        patient can approve it, change its time, give it to a family member, skip it, or stop
        (their place is saved). Medicine items and flagged items stay on the screen.
        """
        service = deps.service
        identity = _patient(deps, ctx)
        voice, screen_only = service.voice_reviewable(identity)
        workflow = service.active_workflow(identity, "plan_review")
        if workflow is None:
            if not voice:
                tail = f" {_plural(screen_only, 'item')} {'is' if screen_only == 1 else 'are'} waiting on your screen." if screen_only else ""
                return _result("There's nothing to review by voice." + tail, view="plan-review")
            workflow = service.start_workflow(identity, "plan_review", [i["id"] for i in voice])
        else:
            # A paused review also picks up drafts imported since it started.
            workflow["queue"] = workflow["queue"] + [i["id"] for i in voice if i["id"] not in workflow["queue"]]
        queue = workflow["queue"]
        helpers = service.task_helpers(identity)
        while workflow["position"] < len(queue):
            item = service.storage.get(identity.patient, queue[workflow["position"]])
            if not item or item.get("status") != "draft":
                workflow["position"] += 1
                continue
            is_task = item["type"] == "PLAN_TASK"
            schema = _review_schema(is_task, helpers)
            options = ("Approve, change the time, " + ("give it to someone, " if helpers else "") + "skip, or stop?"
                       if is_task else "Approve, skip, or stop?")
            prompt = f"Item {workflow['position'] + 1} of {len(queue)}: {_describe(service, item)}. {options}"
            choice = None
            for attempt in range(2):
                reply = await ctx.elicit(prompt if attempt == 0 else
                                         "Sorry, I didn't catch that. Say approve, skip, stop" +
                                         (", or a new time." if is_task else "."), schema)
                if reply.action != "accept":
                    choice = "stop"
                    break
                data = reply.data
                if data.action == "change time" and not getattr(data, "new_time", None):
                    reply = await ctx.elicit("What time should it be?", schema)
                    if reply.action != "accept":
                        choice = "stop"
                        break
                    data = reply.data
                    if not getattr(data, "new_time", None):
                        continue
                if getattr(data, "new_time", None) or getattr(data, "who", None) or data.action:
                    choice = data
                    break
            if choice is None or choice == "stop" or getattr(choice, "action", None) == "stop":
                service.save_workflow(identity, workflow)
                left = len(queue) - workflow["position"]
                return _result(f"Okay, I've saved your place. {_plural(left, 'item')} left. "
                               'Say "continue my review" anytime.', view="plan-review")
            if choice.action == "skip":
                workflow["skipped"] += 1
            else:
                edits = {}
                if getattr(choice, "new_time", None):
                    from ..core import resolve_spoken_time
                    edits["times"] = [resolve_spoken_time(choice.new_time, item.get("times"))]
                service.approve_plan_item(identity, item["id"], edits=edits)
                workflow["approved"] += 1
                who = getattr(choice, "who", None)
                if who and who != "me":
                    grant = service.grant_for_name(identity, who)
                    if grant:
                        service.assign_task(identity, item["id"], grant["id"])
                        workflow["assigned"].append(who)
            workflow["position"] += 1
            workflow = service.save_workflow(identity, workflow)
        workflow["status"] = "done"
        service.save_workflow(identity, workflow)
        speakable = f"Done: {workflow['approved']} approved"
        speakable += f", {workflow['skipped']} skipped." if workflow["skipped"] else "."
        _voice, screen_only = service.voice_reviewable(identity)
        if screen_only:
            speakable += f" {_plural(screen_only, 'item')} {'is' if screen_only == 1 else 'are'} waiting on your screen."
        active = [t for t in service.list_care_tasks(identity) if t["type"] == "PLAN_TASK" and t.get("status") == "active"]
        offer = None if workflow["assigned"] else _assign_offer(service, identity)
        return _result(speakable, view="plan-review", reminders=service.reminder_suggestions(active), next_step=offer)

    @tool("update_task_time", "tasks", _IDEMPOTENT_WRITE)
    @_safe_tool("That task's time couldn't be changed.")
    def update_task_time(task: str, new_time: str, ctx: Context) -> VoiceResult:
        """Patient moves an active task to a new time, as spoken: "8 pm", "20:00" or "9".

        ``task`` = the task's name as the person said it ("the walk"); a ref id also works.
        """
        task = deps.service.update_task_time(_patient(deps, ctx), task, new_time)
        return _result(f"Done. {task.get('label') or 'That task'} is now at {_say_times(task['times'])}.", view="tasks",
                       refs=_plan_refs([task]), reminders=deps.service.reminder_suggestions([task]))

    # ---- family task assignment -------------------------------------------------
    @tool("assign_task", "tasks", _IDEMPOTENT_WRITE)
    @_safe_tool("That task can't be assigned. Check that the family member has permission to do tasks.")
    def assign_task(task: str, ctx: Context, assignee: str | None = None) -> VoiceResult:
        """Patient assigns an active task to a family member, or back to themself.

        ``task`` = the task's name exactly as the person said it ("the dressing"); a ref id also works.
        ``assignee`` = the family member's name ("Sam"), or a caregiver_grant ref id; they must
        have perform_tasks. Omit it to take the task back. The result carries reminder suggestions for
        Alexa+ to create with its own reminders feature.
        """
        task = deps.service.assign_task(_patient(deps, ctx), task, assignee)
        who = task.get("assignee_name")
        when = f" at {_say_times(task['times'])}" if task.get("times") else ""
        speakable = (f"Done. {who} will handle {task.get('label') or 'that task'}{when}." if who
                     else f"Done. You'll handle {task.get('label') or 'that task'} yourself.")
        return _result(speakable, view="tasks", refs=_plan_refs([task]),
                       reminders=deps.service.reminder_suggestions([task]))

    @tool("list_my_assigned_tasks", "tasks", _READ)
    @_safe_tool("Your assigned tasks are unavailable.")
    def list_my_assigned_tasks(ctx: Context) -> VoiceResult:
        """FAMILY MEMBERS ONLY: the patient's tasks assigned to you, with their times.

        Asking for these also clears any new-task notice. The patient asking about their own tasks
        should use list_care_tasks.
        """
        identity = _patient(deps, ctx)
        if identity.role == "patient":
            return list_care_tasks(ctx)  # a patient asking "my tasks" means their own plan
        tasks = deps.service.assigned_tasks(identity)
        if not tasks:
            return _result(f"You don't have any CareLoop tasks to help {deps.service.patient_name(identity.patient)} with.",
                           view="tasks", surface="glance")
        described = [f"{t.get('label') or 'a care task'}" + (f" at {_say_times(t['times'])}" if t.get("times") else "")
                     for t in tasks]
        speakable = (f"You have {_plural(len(tasks), 'task')} to help {deps.service.patient_name(identity.patient)} "
                     f"with: {_join(described)}.")
        return _result(speakable, view="tasks", surface="glance", refs=_plan_refs(tasks),
                       reminders=deps.service.reminder_suggestions(tasks))

    # ---- questions for the clinician ----------------------------------------------
    @tool("add_question_for_clinician", "visit-handoff", _WRITE)
    @_safe_tool("That question couldn't be saved.")
    def add_question_for_clinician(question: str, ctx: Context) -> VoiceResult:
        """Save the patient's question for their clinician. It goes into the next visit handoff.

        CareLoop never answers it, and the reply never repeats the question aloud.
        """
        if CRISIS.search(question):
            return _result(CRISIS_REPLY, view="visit-handoff")  # never filed away for later
        deps.service.add_clinician_question(_patient(deps, ctx), question)
        total = sum(q.get("status", "open") == "open" for q in deps.service.clinician_questions(_patient(deps, ctx)))
        return _result(f"Saved. You have {_plural(total, 'question')} ready for your next appointment.", view="visit-handoff")

    # ---- access transparency ------------------------------------------------------
    @tool("who_accessed_my_care_data", "care-circle", _READ)
    @_safe_tool("The access log is unavailable.")
    def who_accessed_my_care_data(ctx: Context, from_date: int | str = "last_7_days", to_date: int | str | None = None) -> VoiceResult:
        """The access LOG: what other people actually viewed or did with the patient's care data, and how often. Defaults to the last 7 days.

        Use it for "who has seen my care data" or "who looked at my records". It does not list who is
        allowed to see things; list_care_circle does that.
        """
        from ..core import ACCESS_PHRASES
        start, end = _date_range(from_date, to_date, now=int(deps.service.clock()), required=False)
        now = int(deps.service.clock())
        people = deps.service.access_summary(_patient(deps, ctx), start or 0, end or now)
        period = "in the last 7 days" if from_date == "last_7_days" else "in that period"
        if not people:
            return _result(f"No one else accessed your care data {period}.", view="care-circle")
        sentences = []
        for person in people:
            acts = [f"{ACCESS_PHRASES[action]}{'' if n == 1 else f' {n} times'}"
                    for action, n in sorted(person["actions"].items(), key=lambda kv: -kv[1])]
            sentences.append(f"{person['name']} {_join(acts)}")
        return _result(f"{period.capitalize()}, " + "; ".join(sentences) + ".", view="care-circle")

    # ---- care circle ------------------------------------------------------------
    @tool("list_care_circle", "care-circle", _READ)
    @_safe_tool("Care circle is unavailable.")
    def list_care_circle(ctx: Context) -> VoiceResult:
        """Who HAS access: the people the patient invited, what each may do, and their status.

        Use it for "who has access to my care", "who can see my tasks" or "who is in my care circle".
        For what people actually looked at or did, use who_accessed_my_care_data instead.
        """
        grants = deps.service.list_grants(_patient(deps, ctx))
        active = sum(1 for g in grants if g.get("status") == "active")
        pending = sum(1 for g in grants if g.get("status") == "pending")
        return _result(f"Your care circle has {_plural(active, 'active caregiver')} and {_plural(pending, 'pending invitation')}.",
                       view="care-circle", refs=_grant_refs(grants))

    @tool("invite_caregiver", "care-circle", _WRITE)
    @_safe_tool("Caregiver invitation is unavailable.")
    async def invite_caregiver(scopes: list[str], ctx: Context, expires_at: int | str | None = None,
                               name: str | None = None, expires_in_days: int | None = None) -> VoiceResult:
        """Create a patient-controlled caregiver invitation for a family member.

        ``scopes`` ⊆ read_tasks, read_observations, write_observations, receive_alerts,
        acknowledge_alerts, upload_documents, perform_tasks (can be assigned tasks and mark them
        done). ``name`` is the patient's short name for them ("Sam", "Mom"). For "for two weeks"
        use ``expires_in_days`` (14); ``expires_at`` (epoch or ISO-8601) is for an exact date.
        Omit both for no expiry. Grant ONLY what the patient asked for, using this mapping:
        "see my tasks" → read_tasks; "get updates" / "alerts" → receive_alerts and
        acknowledge_alerts; "see my check-ins" → read_observations; "log check-ins for me" →
        write_observations; "upload documents" → upload_documents; "help with" / "do tasks" →
        perform_tasks. CareLoop reads the permissions back and creates nothing unless confirmed.
        """
        if expires_in_days is not None:
            if isinstance(expires_in_days, bool) or not 1 <= int(expires_in_days) <= 366:
                raise ValueError("expiry must be 1-366 days")
            expiry = int(deps.service.clock()) + int(expires_in_days) * 86_400
        else:
            expiry = None if expires_at is None else _date_bound(expires_at, end_of_day=True)
        identity = _patient(deps, ctx)
        if not scopes or any(scope not in PERMISSION_WORDS for scope in scopes):
            raise ValueError("invalid caregiver scope")
        who = name or "This person"
        abilities = _join([PERMISSION_WORDS[scope] for scope in sorted(set(scopes), key=list(PERMISSION_WORDS).index)])
        until = f", for {expires_in_days} days" if expires_in_days else ""
        if hasattr(ctx, "elicit"):
            try:
                answer = await ctx.elicit(f"{who} will be able to {abilities}{until}. Is that right?", ConfirmInvite)
            except Exception:
                answer = None  # no elicitation support: the spoken result still lists the permissions
            if answer is not None and (answer.action != "accept" or not answer.data.confirm):
                return _result("Okay, no invitation was created. Tell me exactly what they should be able to do.",
                               view="care-circle")
        invitation = deps.service.invite(identity, scopes, expiry, name)
        return _result(f"Invitation created: {who} can {abilities}{until}.", view="care-circle",
                       refs=_grant_refs([invitation]))

    @tool("accept_caregiver_invitation", "care-circle", _IDEMPOTENT_WRITE)
    @_safe_tool("That invitation is unavailable.")
    def accept_caregiver_invitation(invitation_id: str, ctx: Context) -> VoiceResult:
        """Caregiver accepts an unexpired invitation, binding it to their own authenticated identity."""
        grant = deps.service.accept_invitation(_patient(deps, ctx), invitation_id)
        return _result("Invitation accepted. You now have the access the patient chose.", view="care-circle",
                       refs=[{"id": grant["id"], "kind": "caregiver_grant", "status": grant["status"],
                              "label": "your access", "scopes": list(grant.get("scopes", []))}])

    @tool("revoke_caregiver", "care-circle", _DESTRUCTIVE)
    @_safe_tool("That caregiver access can't be revoked.")
    def revoke_caregiver(ctx: Context, caregiver: str | None = None, invitation_id: str | None = None) -> VoiceResult:
        """Revoke one family member's access. The host asks the person to confirm before this runs, so call it directly.

        ``caregiver`` = the name the person used ("Sam"). Or pass ``invitation_id`` (a ref id from
        list_care_circle). Never ask the person for an id.
        """
        patient = _patient(deps, ctx)
        if invitation_id is None:
            if not caregiver:
                raise ValueError("a caregiver name or reference is required")
            invitation_id = deps.service.grant_by_name(patient, caregiver)["id"]
        if not deps.service.revoke(patient, invitation_id=invitation_id):
            raise ValueError("no matching grant")
        return _result("Caregiver access revoked. It stops on their next request.", view="care-circle")

    # ---- caregiver notifications ------------------------------------------------
    @tool("list_generic_notifications", "notifications", _READ)
    @_safe_tool("CareLoop notifications are unavailable.")
    def list_generic_notifications(ctx: Context) -> VoiceResult:
        """Caregiver: what is new for you, as counts only: CareLoop updates, and new tasks the patient gave you.

        No alert detail and no task name is ever included. For the task itself, call list_my_assigned_tasks.
        """
        identity = _patient(deps, ctx)
        cases = deps.service.notifications(identity)
        updates = [c for c in cases if c.get("kind") != "task_assigned"]
        notices = [c for c in cases if c.get("kind") == "task_assigned"]
        new_updates = [c for c in updates if c["status"] == "action_required"]
        new_tasks = [c for c in notices if c["status"] == "action_required"]
        parts = []
        if new_updates:
            parts.append(_plural(len(new_updates), "new CareLoop update"))
        if new_tasks:
            parts.append(f"{_plural(len(new_tasks), 'new task')} from {deps.service.patient_name(identity.patient)}")
        speakable = f"You have {' and '.join(parts)}." if parts else "There are no new CareLoop updates."
        refs = [{"id": c["case_id"], "kind": "update", "status": c["status"], "label": f"update {i}"}
                for i, c in enumerate(updates, start=1)]
        refs += [{"id": c["case_id"], "kind": "assigned_task", "status": c["status"], "label": f"new task {i}"}
                 for i, c in enumerate(notices, start=1)]
        return _result(speakable, view="notifications", surface="glance", refs=refs)

    @tool("acknowledge_alert", "notifications", _IDEMPOTENT_WRITE)
    @_safe_tool("That CareLoop update can't be acknowledged.")
    def acknowledge_alert(ctx: Context, alert_id: str | None = None) -> VoiceResult:
        """Caregiver: mark generic CareLoop updates as seen, without reading their private detail.

        Call it with no arguments for "mark it seen" or "got it": it marks the updates and new-task notices still waiting.
        ``alert_id`` (a ref from list_generic_notifications) is optional. Never ask the person for an id.
        """
        identity = _patient(deps, ctx)
        if alert_id is None:
            # Everything waiting that this person is allowed to clear. An alert needs the acknowledge permission,
            # a new-task notice needs only perform_tasks, so one of them may be skipped.
            acknowledgements = []
            for row in deps.service.notifications(identity):
                if row["status"] != "action_required":
                    continue
                try:
                    acknowledgements.append(deps.service.acknowledge_alert(identity, row["case_id"]))
                except AccessDenied:
                    continue
            if not acknowledgements:
                raise ValueError("no update is waiting")
        else:
            acknowledgements = [deps.service.acknowledge_alert(identity, alert_id)]
        only_tasks = all(ack.get("kind") == "task_assigned" for ack in acknowledgements)
        speakable = ("Marked as seen." if only_tasks else
                     "CareLoop update acknowledged." if len(acknowledgements) == 1 else "CareLoop updates acknowledged.")
        return _result(speakable, view="notifications", surface="glance",
                       refs=[{"id": ack["case_id"], "kind": "assigned_task" if ack.get("kind") == "task_assigned" else "update",
                              "status": ack["status"], "label": "seen" if ack.get("kind") == "task_assigned" else "acknowledged update"}
                             for ack in acknowledgements])

    # ---- observations, history, handoff ------------------------------------------
    @tool("start_daily_checkin", "check-in-trend", _WRITE)
    @_safe_tool("The check-in couldn't be completed. Nothing was recorded.")
    async def start_daily_checkin(ctx: Context) -> VoiceResult:
        """Start the person's daily check-in. CareLoop asks its own follow-up question(s)
        through MCP elicitation, so call this with no arguments when someone says
        "do my check-in" without giving a value."""
        identity = _patient(deps, ctx)
        if identity.role == "caregiver":
            # Fail before asking anything a caregiver may not be allowed to answer.
            deps.service.patient_for(identity, "write_observations")
        try:
            answer = await ctx.elicit(CHECKIN_QUESTION, PainCheckIn)
        except Exception as exc:  # the client may not support elicitation
            raise ValueError("elicitation unavailable") from exc
        if answer.action != "accept":
            return _result("Okay, I skipped today's check-in. Nothing was recorded.", view="check-in-trend")
        record = deps.service.record_observation(identity, pain_score=answer.data.pain_score,
                                                 idempotency_key=f"checkin-{uuid.uuid4().hex}")
        refs: list[Ref] = [{"id": record["id"], "kind": "observation", "label": "latest check-in"}]
        if identity.role == "caregiver":
            return _result("Check-in recorded.", view="check-in-trend", refs=refs)
        # Follow-up questions come from the approved plan: the patient's own tasks not yet done today.
        mine, family = deps.service.checkin_tasks(identity)
        done, todo, stopped = [], [], False
        for task in mine:
            label = task.get("label") or "your task"
            try:
                reply = await ctx.elicit(f"Did you do {label} today?", TaskDone)
            except Exception:
                break
            if reply.action != "accept":
                stopped = True
                break
            if reply.data.done:
                deps.service.record_task_completion(identity, task["id"])
                done.append(label)
            else:
                todo.append(label)
        speakable = "Check-in recorded."
        asked = len(done) + len(todo)
        if asked:
            speakable += f" You did {len(done)} of {_plural(asked, 'task')}."
        if todo:
            speakable += f" {_join(todo)} {'is' if len(todo) == 1 else 'are'} still to do."
        if stopped:
            speakable += " I saved what you told me."
        by_person: dict[str, list[str]] = {}
        for t in family[:4]:
            by_person.setdefault(t.get("assignee_name") or "A family member", []).append(
                (t.get("label") or "a task") + (f" at {_say_times(t['times'])}" if t.get("times") else ""))
        if by_person:
            speakable += " " + " ".join(f"{who} has {_join(items)}." for who, items in by_person.items())
        return _result(speakable, view="check-in-trend", refs=refs)

    @tool("start_teach_back", "teach-back", _WRITE)
    @_safe_tool("Teach-back is unavailable.")
    async def start_teach_back(ctx: Context) -> VoiceResult:
        """Check the patient understood their approved plan ("check I understood my plan", "quiz me on my
        plan", "teach-back", "check my understanding"). CareLoop asks the person to say back key values (when
        or how often a medicine is taken, the alert rule's numbers, a warning sign's number) through MCP
        elicitation and checks every answer itself, so call this with no arguments. It continues a paused
        session. This is not the daily check-in and not the task list.
        """
        from ..teach_back import expected_for, interpret, is_dont_know, is_stop, matches, question_for
        service = deps.service
        identity = _patient(deps, ctx)
        checks = {f"{c['item']['id']}:{c['check']}": c for c in service.teach_back_checks(identity)}
        workflow = service.active_workflow(identity, "teach_back")
        if workflow is None:
            if not checks:
                return _result("There's nothing in your plan to check yet. Medicines, alert rules and warning signs "
                               "can be checked once they're approved.", view="teach-back")
            # Ask what isn't understood yet (never checked, or needs another look); if all is, check it all again.
            latest = {(r["item_id"], r["check"]): r["result"] for r in service.teach_back_results(identity)}
            due = [key for key, c in checks.items() if latest.get((c["item"]["id"], c["check"])) != "understood"] or list(checks)
            workflow = service.start_workflow(identity, "teach_back", due) | {"right": 0, "asked": 0, "missed_streak": 0}
            say = f"Let's check {_plural(len(due), 'thing')}. "
        else:
            # A paused session also picks up plan values approved since it started.
            workflow["queue"] = workflow["queue"] + [key for key in checks if key not in workflow["queue"]]
            say = "Let's pick up where we left off. "
        queue = workflow["queue"]
        while workflow["position"] < len(queue):
            entry = checks.get(queue[workflow["position"]])
            if entry is None:  # the item was changed or removed since the session started
                workflow["position"] += 1
                continue
            item, check = entry["item"], entry["check"]
            expected, question = expected_for(item, check), question_for(item, check)
            prompt, heard, attempts, result = say + question, None, 0, "needs_clarification"
            while attempts < TEACH_BACK_ATTEMPTS:
                try:
                    reply = await ctx.elicit(prompt, TeachBackAnswer)
                except Exception as exc:  # the client may not support elicitation
                    raise ValueError("elicitation unavailable") from exc
                if reply.action != "accept" or is_stop(reply.data.answer):
                    service.save_workflow(identity, workflow)
                    left = len(queue) - workflow["position"]
                    return _result(f"Okay, I've saved your place. {_plural(left, 'question')} left. "
                                   'Say "check my understanding" anytime.', view="teach-back")
                attempts += 1
                if is_dont_know(reply.data.answer):
                    heard = None
                    break
                heard = interpret(check, reply.data.answer, expected)
                if matches(check, expected, heard):
                    result = "understood"
                    break
                prompt = f"Not quite. Try again: {question}"
            service.record_teach_back(identity, item, check, result=result, attempts=attempts, expected=expected,
                                      heard=heard, session_id=workflow["id"])
            workflow["asked"] += 1
            if result == "understood":
                workflow["right"] += 1
                workflow["missed_streak"] = 0
                say = "That's right. "
            else:
                workflow["missed_streak"] += 1
                # Read the plan back in its own words. Never a reason, never advice.
                comfort = "That's okay. " if heard is None else ""
                say = f"{comfort}Your plan says: {_describe(service, item)}. Next: "
            workflow["position"] += 1
            workflow = service.save_workflow(identity, workflow)
            if workflow["missed_streak"] >= TEACH_BACK_MISS_LIMIT and workflow["position"] < len(queue):
                for key in queue[workflow["position"]:]:
                    if key in checks:
                        rest = checks[key]
                        service.record_teach_back(identity, rest["item"], rest["check"], result="skipped", attempts=0,
                                                  expected=expected_for(rest["item"], rest["check"]), heard=None,
                                                  session_id=workflow["id"])
                workflow |= {"status": "done", "position": len(queue)}
                service.save_workflow(identity, workflow)
                return _result(f"Let's leave the rest for your clinician. You got {workflow['right']} of "
                               f"{workflow['asked']} right, and I've noted it for your visit handoff.", view="teach-back")
        workflow["status"] = "done"
        service.save_workflow(identity, workflow)
        missed = workflow["asked"] - workflow["right"]
        speakable = ("That's right. " if say == "That's right. " else "") + f"Done. You got {workflow['right']} of {workflow['asked']} right."
        if missed == 1:
            speakable += " The one to look at again is on your screen, with the line it came from."
        elif missed:
            speakable += " The ones to look at again are on your screen, with the lines they came from."
        return _result(speakable, view="teach-back")

    @tool("record_pain_observation", "check-in-trend", _IDEMPOTENT_WRITE)
    @_safe_tool("Observation is unavailable.")
    def record_pain_observation(pain_score: int, ctx: Context, idempotency_key: str | None = None,
                                observed_at: int | str | None = None) -> VoiceResult:
        """Record a synthetic integer pain score from 0 through 10; this does not interpret it.

        A spoken number word counts ("four" is 4). ``idempotency_key`` is optional: leave it out unless
        you are retrying the same call. Never ask the person for it.
        """
        when = None if observed_at is None else _date_bound(observed_at, end_of_day=False)
        record = deps.service.record_observation(_patient(deps, ctx), pain_score=pain_score, observed_at=when,
                                                 idempotency_key=idempotency_key or f"voice-{uuid.uuid4().hex}")
        return _result("Check-in recorded.", view="check-in-trend",
                       refs=[{"id": record["id"], "kind": "observation", "label": "latest check-in"}])

    @tool("correct_pain_observation", "check-in-trend", _IDEMPOTENT_WRITE)
    @_safe_tool("Observation correction is unavailable.")
    def correct_pain_observation(observation_id: str, pain_score: int, ctx: Context, idempotency_key: str | None = None,
                                 observed_at: int | str | None = None) -> VoiceResult:
        """Create an immutable correction for one prior observation (ref id). ``idempotency_key`` is optional; never ask for it."""
        when = None if observed_at is None else _date_bound(observed_at, end_of_day=False)
        record = deps.service.record_observation(_patient(deps, ctx), pain_score=pain_score, observed_at=when,
                                                 idempotency_key=idempotency_key or f"voice-{uuid.uuid4().hex}", corrects_id=observation_id)
        return _result("Correction recorded. The original stays in your history.", view="check-in-trend",
                       refs=[{"id": record["id"], "kind": "observation", "label": "correction"}])

    @tool("list_care_records", "records", _READ)
    @_safe_tool("CareLoop records are unavailable.")
    def list_care_records(ctx: Context, record_type: str | None = None) -> VoiceResult:
        """List counts and ref ids of the caller's authorized CareLoop records.

        ``record_type`` is optional; a plain kind works ("pain check-in", "care task"). Refs are
        labelled by kind, oldest first, with the newest of each kind called "latest ..." (for example
        "latest pain check-in"). Use them to pick the record for delete_care_record.
        """
        records = deps.service.list_records(_patient(deps, ctx), _record_type(record_type))
        return _result(f"Found {_plural(len(records), 'CareLoop record')}.", view="records", refs=_record_refs(records))

    @tool("search_care_history", "history", _READ)
    @_safe_tool("CareLoop history search is unavailable.")
    def search_care_history(query: str, ctx: Context, from_date: int | str | None = None, to_date: int | str | None = None) -> VoiceResult:
        """Search the caller's authorized, source-linked records.

        Call this for ANY question about a person's pain scores, check-ins or history, including from a
        family member on a shared speaker. The server decides what may be spoken; never answer such a
        question yourself.

        Dates accept epoch, ISO-8601, or ``from_date="last_N_days"``.
        Matches are listed as refs and shown in the private history view.
        """
        start, end = _date_range(from_date, to_date, now=int(deps.service.clock()), required=False)
        identity = _patient(deps, ctx)
        if identity.role == "caregiver" and _ABOUT_VALUES.search(query):
            # A family member asking about scores or check-ins needs that access. Without it, even a count
            # of plan text that mentions pain would sound like an answer on a shared speaker.
            try:
                deps.service.patient_for(identity, "read_observations")
            except AccessDenied:
                raise ToolError("CareLoop records are unavailable.") from None  # the same words as listing records
        matches = deps.service.search(identity, query, from_date=start, to_date=end)
        speakable = f"Found {_plural(len(matches), 'matching record')}." if matches else "No matching record found."
        return _result(speakable, view="history",
                       refs=[{"id": r["id"], "kind": r["type"].lower(), "label": f"match {i}"}
                             for i, r in enumerate(matches, start=1)])

    @tool("create_visit_handoff", "visit-handoff", _WRITE)
    @_safe_tool("Visit handoff is unavailable.")
    def create_visit_handoff(from_date: int | str, ctx: Context, to_date: int | str | None = None) -> VoiceResult:
        """Prepare the visit handoff: the dated, cited summary for a doctor or clinic appointment.

        Use it for "get me ready for my appointment", "prepare for my doctor visit" or "a summary for
        my clinician". Do not use export_care_data for that. For an appointment with no dates given,
        call it with ``from_date="last_7_days"``.

        ISO calendar dates are inclusive UTC bounds.  A relative range ends
        now and must be supplied as ``from_date`` without ``to_date``.
        """
        from_epoch, to_epoch = _handoff_dates(from_date, to_date, now=int(deps.service.clock()))
        handoff = deps.service.create_visit_handoff(_patient(deps, ctx), from_epoch, to_epoch)
        questions = handoff.get("totals", {}).get("questions", 0)
        speakable = "Your visit handoff is ready on your private screen."
        if questions:
            speakable += f" It includes {_plural(questions, 'question')} for your clinician."
        return _result(speakable, view="visit-handoff",
                       refs=[{"id": handoff["id"], "kind": "handoff", "label": "visit handoff"}])

    # ---- data rights -------------------------------------------------------------
    @tool("export_care_data", "export", _READ)
    @_safe_tool("CareLoop export is unavailable.")
    def export_care_data(ctx: Context) -> VoiceResult:
        """Data rights only: prepare a copy of ALL of the patient's records when they ask to export, download or get a copy of their data.

        Never use it to prepare for an appointment or a doctor visit (that is create_visit_handoff).
        """
        exported = deps.service.export(_patient(deps, ctx))
        return _result(f"Your export of {_plural(exported['count'], 'record')} is ready on your private screen.", view="export")

    @tool("delete_care_record", "records", _DESTRUCTIVE)
    @_safe_tool("No active CareLoop record was deleted.")
    def delete_care_record(record_id: str, ctx: Context) -> VoiceResult:
        """Delete one patient record and its derived retrieval entries. The host asks the person to confirm before this runs, so call it directly.

        ``record_id`` = a ref id from list_care_records; its label (for example "latest pain check-in")
        also works. Look it up first; never ask the person for an id.
        """
        patient = _patient(deps, ctx)
        if not deps.service.delete(patient, _resolve_record(deps, patient, record_id)):
            raise ValueError("no active record")
        return _result("Care record deleted.", view="records")

    # ---- MCP App data channel ----------------------------------------------------
    from ..ui import VIEWS, view_details

    @tool("get_private_view", "", _READ, app_only=True)
    @_safe_tool("This CareLoop view is unavailable.")
    def get_private_view(view: str, ctx: Context, record_ids: list[str] | None = None) -> dict:
        """App-only: detailed data for a CareLoop MCP App view. Never speak or summarize this result."""
        if view not in VIEWS:
            raise ValueError("unknown view")
        return {"view": view, "synthetic": True, "data": view_details(deps, _patient(deps, ctx), view, record_ids or [])}
