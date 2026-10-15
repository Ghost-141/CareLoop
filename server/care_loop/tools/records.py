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
from pydantic import BaseModel, Field

from ..core import AccessDenied


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
    times: NotRequired[list[str]]  # a task's scheduled local times, e.g. "20:00"
    assignee: NotRequired[str]


class Reminder(TypedDict):
    """A reminder Alexa+ should create with its own native feature. CareLoop never schedules it."""
    task_id: str
    label: str
    times: list[str]
    to: str  # "patient", or the family member's name


class VoiceResult(TypedDict):
    status: Literal["ok"]
    speakable: str
    surface: Surface
    view: str
    refs: list[Ref]
    reminders: NotRequired[list[Reminder]]


def _view_uri(view: str) -> str:
    return f"ui://careloop/{view}"


def _result(speakable: str, *, view: str, refs: list[Ref] | None = None, surface: Surface = "private_screen",
            reminders: list[dict[str, Any]] | None = None) -> VoiceResult:
    result: VoiceResult = {"status": "ok", "speakable": speakable, "surface": surface, "view": _view_uri(view), "refs": refs or []}
    if reminders:
        result["reminders"] = [{"task_id": r["task_id"], "label": r["label"], "times": r["times"], "to": r["for"]}
                               for r in reminders]
    return result


def _join(parts: list[str]) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


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
                except (ToolError, AccessDenied, ValueError, OverflowError) as exc:
                    raise ToolError(message) from exc
            return safe_async

        @wraps(function)
        def safe(*args, **kwargs):
            try:
                return function(*args, **kwargs)
            except (ToolError, AccessDenied, ValueError, OverflowError) as exc:
                raise ToolError(message) from exc
        return safe
    return decorate


class PainCheckIn(BaseModel):
    """Elicitation schema for the daily check-in: one validated, uninterpreted value."""
    pain_score: int = Field(ge=0, le=10, description="Pain score today, a whole number from 0 (none) to 10 (worst)")


CHECKIN_QUESTION = "On a scale from 0 to 10, what's your pain score today?"


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
        refs.append(ref)
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


def _patient(deps, ctx):
    try:
        return deps.identity(ctx)
    except AccessDenied as exc:
        raise ToolError("Not authorized for this CareLoop patient.") from exc


_READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
_WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
_IDEMPOTENT_WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
_DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)


def _ui(view: str, *, app_only: bool = False) -> dict[str, Any]:
    if app_only:
        # MCP Apps visibility: callable by a rendered view, hidden from the model.
        return {"ui": {"visibility": ["app"]}}
    return {"ui": {"resourceUri": _view_uri(view)}}


def register(mcp: MCPServer, deps) -> None:
    def tool(name: str, view: str, annotations: ToolAnnotations, *, app_only: bool = False):
        return mcp.tool(name=name, annotations=annotations, meta=_ui(view, app_only=app_only))

    # ---- plan intake and review -------------------------------------------------
    @tool("import_care_plan_text", "plan-review", _WRITE)
    @_safe_tool("Care plan import is unavailable.")
    def import_care_plan_text(title: str, text: str, ctx: Context) -> VoiceResult:
        """Import bounded synthetic plan text as patient-owned drafts for review.

        The original text is not retained; only extracted, source-cited
        directives become drafts and still require explicit patient approval
        (``approve_plan_item`` with a returned ref id).
        """
        intake = deps.service.intake_text_document(_patient(deps, ctx), title, text)
        drafts = intake["drafts"]
        reviewable = sum(1 for draft in drafts if draft.get("status") == "draft")
        speakable = f"Imported {_plural(len(drafts), 'plan item')} for your review."
        if intake["manual_review_required"]:
            speakable += " Some instructions need manual review before they can be approved."
        elif reviewable:
            speakable += " Approve each item on your screen to activate it."
        return _result(speakable, view="plan-review", refs=_plan_refs(drafts))

    @tool("approve_plan_item", "plan-review", _IDEMPOTENT_WRITE)
    @_safe_tool("That item needs your review on screen before it can be approved.")
    def approve_plan_item(record_id: str, ctx: Context) -> VoiceResult:
        """Patient-confirm one source-cited draft (a ref id from list/import) so it becomes active.

        Medicine items and items flagged for review can only be approved on the patient's screen.
        """
        item = deps.service.approve_plan_item(_patient(deps, ctx), record_id)
        reminders = deps.service.reminder_suggestions([item])
        kind = {"PLAN_RULE": "rule", "PLAN_NOTE": "note"}.get(item["type"], "task")
        return _result(f"Plan {kind} approved and now active.", view="plan-review", refs=_plan_refs([item]),
                       reminders=reminders)

    @tool("list_care_tasks", "tasks", _READ)
    @_safe_tool("Care tasks are unavailable.")
    def list_care_tasks(ctx: Context) -> VoiceResult:
        """List counts and ref ids of the person's plan tasks/rules.

        Patients also see their own unapproved drafts; caregivers never receive
        draft instructions.  Task wording is shown only in the private view.
        """
        items = deps.service.list_care_tasks(_patient(deps, ctx))
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
        return _result(speakable, view="plan-review", refs=refs + _plan_refs(pending))

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

    # ---- family task assignment -------------------------------------------------
    @tool("assign_task", "tasks", _IDEMPOTENT_WRITE)
    @_safe_tool("That task can't be assigned. Check that the family member has permission to do tasks.")
    def assign_task(task_id: str, ctx: Context, assignee_id: str | None = None) -> VoiceResult:
        """Patient assigns an active task (ref id) to a family member, or back to themself.

        ``assignee_id`` = a caregiver_grant ref id from ``list_care_circle`` whose scopes include
        perform_tasks; omit it to take the task back. The result carries reminder suggestions for
        Alexa+ to create with its own reminders feature.
        """
        task = deps.service.assign_task(_patient(deps, ctx), task_id, assignee_id)
        who = task.get("assignee_name")
        when = f" at {_join(task['times'])}" if task.get("times") else ""
        speakable = (f"Done. {who} will handle {task.get('label') or 'that task'}{when}." if who
                     else f"Done. You'll handle {task.get('label') or 'that task'} yourself.")
        return _result(speakable, view="tasks", refs=_plan_refs([task]),
                       reminders=deps.service.reminder_suggestions([task]))

    @tool("list_my_assigned_tasks", "tasks", _READ)
    @_safe_tool("Your assigned tasks are unavailable.")
    def list_my_assigned_tasks(ctx: Context) -> VoiceResult:
        """Family member: the patient's tasks assigned to you, with their times (never the cited instructions)."""
        tasks = deps.service.assigned_tasks(_patient(deps, ctx))
        if not tasks:
            return _result("You don't have any CareLoop tasks assigned to you.", view="tasks", surface="glance")
        described = [f"{t.get('label') or 'a care task'}" + (f" at {_join(t['times'])}" if t.get("times") else "")
                     for t in tasks]
        speakable = f"You have {_plural(len(tasks), 'task')} to help with: {_join(described)}."
        return _result(speakable, view="tasks", surface="glance", refs=_plan_refs(tasks),
                       reminders=deps.service.reminder_suggestions(tasks))

    # ---- questions for the clinician ----------------------------------------------
    @tool("add_question_for_clinician", "visit-handoff", _WRITE)
    @_safe_tool("That question couldn't be saved.")
    def add_question_for_clinician(question: str, ctx: Context) -> VoiceResult:
        """Save the patient's question for their clinician. It goes into the next visit handoff.

        CareLoop never answers it, and the reply never repeats the question aloud.
        """
        deps.service.add_clinician_question(_patient(deps, ctx), question)
        total = sum(q.get("status", "open") == "open" for q in deps.service.clinician_questions(_patient(deps, ctx)))
        return _result(f"Saved. You have {_plural(total, 'question')} ready for your next appointment.", view="visit-handoff")

    # ---- access transparency ------------------------------------------------------
    @tool("who_accessed_my_care_data", "care-circle", _READ)
    @_safe_tool("The access log is unavailable.")
    def who_accessed_my_care_data(ctx: Context, from_date: int | str = "last_7_days", to_date: int | str | None = None) -> VoiceResult:
        """Patient: who else looked at or acted on their care data, and how often. Defaults to the last 7 days."""
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
        """List the patient's caregiver invitations and grants with scopes and status."""
        grants = deps.service.list_grants(_patient(deps, ctx))
        active = sum(1 for g in grants if g.get("status") == "active")
        pending = sum(1 for g in grants if g.get("status") == "pending")
        return _result(f"Your care circle has {_plural(active, 'active caregiver')} and {_plural(pending, 'pending invitation')}.",
                       view="care-circle", refs=_grant_refs(grants))

    @tool("invite_caregiver", "care-circle", _WRITE)
    @_safe_tool("Caregiver invitation is unavailable.")
    def invite_caregiver(scopes: list[str], ctx: Context, expires_at: int | str | None = None,
                         name: str | None = None) -> VoiceResult:
        """Create a patient-controlled caregiver invitation for a family member.

        ``scopes`` ⊆ read_tasks, read_observations, write_observations, receive_alerts,
        acknowledge_alerts, upload_documents, perform_tasks (can be assigned tasks and mark them
        done). ``name`` is the patient's short name for them ("Sam", "Mom"). ``expires_at``
        accepts epoch or ISO-8601. Share the returned invitation ref id with the caregiver.
        """
        expiry = None if expires_at is None else _date_bound(expires_at, end_of_day=True)
        invitation = deps.service.invite(_patient(deps, ctx), scopes, expiry, name)
        return _result(f"Invitation created with {_plural(len(invitation['scopes']), 'permission')}.",
                       view="care-circle", refs=_grant_refs([invitation]))

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
    def revoke_caregiver(invitation_id: str, ctx: Context) -> VoiceResult:
        """Immediately revoke one caregiver invitation or grant (ref id). Confirm with the patient first."""
        if not deps.service.revoke(_patient(deps, ctx), invitation_id=invitation_id):
            raise ValueError("no matching grant")
        return _result("Caregiver access revoked. It stops on their next request.", view="care-circle")

    # ---- caregiver notifications ------------------------------------------------
    @tool("list_generic_notifications", "notifications", _READ)
    @_safe_tool("CareLoop notifications are unavailable.")
    def list_generic_notifications(ctx: Context) -> VoiceResult:
        """Caregiver: list generic CareLoop update cases (no alert detail is ever included)."""
        cases = deps.service.notifications(_patient(deps, ctx))
        new = [case for case in cases if case["status"] == "action_required"]
        speakable = (f"You have {_plural(len(new), 'new CareLoop update')}." if new
                     else "There are no new CareLoop updates.")
        return _result(speakable, view="notifications", surface="glance",
                       refs=[{"id": case["case_id"], "kind": "update", "status": case["status"], "label": f"update {i}"}
                             for i, case in enumerate(cases, start=1)])

    @tool("acknowledge_alert", "notifications", _IDEMPOTENT_WRITE)
    @_safe_tool("That CareLoop update can't be acknowledged.")
    def acknowledge_alert(alert_id: str, ctx: Context) -> VoiceResult:
        """Caregiver: acknowledge one generic update (ref id) without reading its private detail."""
        acknowledgement = deps.service.acknowledge_alert(_patient(deps, ctx), alert_id)
        return _result("CareLoop update acknowledged.", view="notifications", surface="glance",
                       refs=[{"id": acknowledgement["case_id"], "kind": "update", "status": acknowledgement["status"],
                              "label": "acknowledged update"}])

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
        return _result("Check-in recorded.", view="check-in-trend",
                       refs=[{"id": record["id"], "kind": "observation", "label": "latest check-in"}])

    @tool("record_pain_observation", "check-in-trend", _IDEMPOTENT_WRITE)
    @_safe_tool("Observation is unavailable.")
    def record_pain_observation(pain_score: int, idempotency_key: str, ctx: Context, observed_at: int | str | None = None) -> VoiceResult:
        """Record a synthetic integer pain score from 0 through 10; this does not interpret it."""
        when = None if observed_at is None else _date_bound(observed_at, end_of_day=False)
        record = deps.service.record_observation(_patient(deps, ctx), pain_score=pain_score, observed_at=when, idempotency_key=idempotency_key)
        return _result("Check-in recorded.", view="check-in-trend",
                       refs=[{"id": record["id"], "kind": "observation", "label": "latest check-in"}])

    @tool("correct_pain_observation", "check-in-trend", _IDEMPOTENT_WRITE)
    @_safe_tool("Observation correction is unavailable.")
    def correct_pain_observation(observation_id: str, pain_score: int, idempotency_key: str, ctx: Context, observed_at: int | str | None = None) -> VoiceResult:
        """Create an immutable correction for one prior observation (ref id)."""
        when = None if observed_at is None else _date_bound(observed_at, end_of_day=False)
        record = deps.service.record_observation(_patient(deps, ctx), pain_score=pain_score, observed_at=when,
                                                 idempotency_key=idempotency_key, corrects_id=observation_id)
        return _result("Correction recorded. The original stays in your history.", view="check-in-trend",
                       refs=[{"id": record["id"], "kind": "observation", "label": "correction"}])

    @tool("list_care_records", "records", _READ)
    @_safe_tool("CareLoop records are unavailable.")
    def list_care_records(ctx: Context, record_type: str | None = None) -> VoiceResult:
        """List counts and ref ids of the caller's authorized CareLoop records."""
        records = deps.service.list_records(_patient(deps, ctx), record_type)
        return _result(f"Found {_plural(len(records), 'CareLoop record')}.", view="records",
                       refs=[{"id": r["id"], "kind": r["type"].lower(), "label": f"record {i}"}
                             for i, r in enumerate(records, start=1)])

    @tool("search_care_history", "history", _READ)
    @_safe_tool("CareLoop history search is unavailable.")
    def search_care_history(query: str, ctx: Context, from_date: int | str | None = None, to_date: int | str | None = None) -> VoiceResult:
        """Search the caller's authorized, source-linked records.

        Dates accept epoch, ISO-8601, or ``from_date="last_N_days"``.
        Matches are listed as refs and shown in the private history view.
        """
        start, end = _date_range(from_date, to_date, now=int(deps.service.clock()), required=False)
        matches = deps.service.search(_patient(deps, ctx), query, from_date=start, to_date=end)
        speakable = f"Found {_plural(len(matches), 'matching record')}." if matches else "No matching record found."
        return _result(speakable, view="history",
                       refs=[{"id": r["id"], "kind": r["type"].lower(), "label": f"match {i}"}
                             for i, r in enumerate(matches, start=1)])

    @tool("create_visit_handoff", "visit-handoff", _WRITE)
    @_safe_tool("Visit handoff is unavailable.")
    def create_visit_handoff(from_date: int | str, ctx: Context, to_date: int | str | None = None) -> VoiceResult:
        """Create a handoff from ISO dates, epochs, or a relative range like ``last_7_days``.

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
        """Prepare an export of only the authenticated patient's active records in the private view."""
        exported = deps.service.export(_patient(deps, ctx))
        return _result(f"Your export of {_plural(exported['count'], 'record')} is ready on your private screen.", view="export")

    @tool("delete_care_record", "records", _DESTRUCTIVE)
    @_safe_tool("No active CareLoop record was deleted.")
    def delete_care_record(record_id: str, ctx: Context) -> VoiceResult:
        """Delete one patient record (ref id) and its derived retrieval entries. Confirm with the patient first."""
        if not deps.service.delete(_patient(deps, ctx), record_id):
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
