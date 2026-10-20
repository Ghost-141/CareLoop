"""MCP App views for the private CareLoop screens.

Each ``ui://careloop/<view>`` resource is a static, data-free HTML shell, so a
host may preload or cache it safely.  After the MCP Apps handshake the shell
receives the triggering tool result (counts and opaque refs only) and asks the
app-only ``get_private_view`` tool for detail.  That call runs the same bearer
identity and consent-scope checks as every other tool.
"""
from __future__ import annotations

from importlib.resources import files
from typing import Any

from mcp.server.mcpserver import MCPServer

from ..core import AccessDenied


MIME = "text/html;profile=mcp-app"
VIEWS = {
    "plan-review": "Plan review",
    "tasks": "Care tasks",
    "plan-source": "Plan source",
    "care-circle": "Care circle",
    "notifications": "CareLoop updates",
    "records": "CareLoop records",
    "history": "History search",
    "check-in-trend": "Check-in trend",
    "visit-handoff": "Visit handoff",
    "teach-back": "Understanding check",
    "export": "Data export",
}


def _with_citations(deps: Any, identity: Any, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cache: dict[str, Any] = {}
    rows = []
    for item in items:
        row = dict(item)
        if item.get("source"):
            # Intake drafts carry their own cited lines (with OCR method and confidence).
            title = None
            if item.get("source_id"):
                try:
                    title = deps.service.source_excerpt(identity, item["source_id"])["title"]
                except AccessDenied:
                    title = None
            row["citation"] = {"title": title or "Uploaded document",
                               "excerpts": [{"page": line["page"], "excerpt": line["text"], "line_id": line["id"],
                                             "method": line["method"], "confidence_pct": line["confidence_pct"]}
                                            for line in item["source"]]}
            rows.append(row)
            continue
        source_id = item.get("source_id")
        if source_id and source_id not in cache:
            try:
                cache[source_id] = deps.service.source_excerpt(identity, source_id)
            except AccessDenied:
                cache[source_id] = None
        if source_id and cache.get(source_id):
            page, text = item.get("page"), str(item.get("text", "")).strip()
            excerpts = [e for e in cache[source_id]["page_excerpts"] if page is None or e.get("page") == page]
            # Cite the excerpt this item was extracted from, not every excerpt on its page.
            matching = [e for e in excerpts if text and text in str(e.get("excerpt", ""))]
            row["citation"] = {"title": cache[source_id]["title"], "excerpts": (matching or excerpts)[:1]}
        rows.append(row)
    return rows


def _document_order(item: dict[str, Any]) -> tuple:
    """Review in the order the document reads: by first cited page and line, then creation time."""
    first = (item.get("source") or [{}])[0]
    line_id = str(first.get("id", ""))
    number = int(line_id.split(":L")[1]) if ":L" in line_id else 0
    return (item.get("created_at", 0) // 60, first.get("page", 0), number, item.get("order", 0), item.get("created_at", 0))


def _active_rules(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in items if item["type"] == "PLAN_RULE" and item.get("status") == "active" and item.get("rule_spec")]


def _rule_thresholds(items: list[dict[str, Any]]) -> list[int]:
    return sorted({item["rule_spec"]["threshold"] for item in _active_rules(items)})


def _citation(service: Any, identity: Any, record: dict[str, Any] | None) -> dict[str, Any] | None:
    """A record's document lines in the shape the screen renders (title and excerpts)."""
    found = service.citation(identity.patient, record)
    return {"title": found["title"], "excerpts": found["page_excerpts"]} if found else None


def _because(service: Any, identity: Any, suggestion: dict[str, Any]) -> dict[str, Any]:
    """Why a suggestion was raised: the record it was computed from, and that record's document lines."""
    source = suggestion.get("source") or {}
    record = service.storage.get(identity.patient, source["id"]) if source.get("id") else None
    kind = suggestion["kind"]
    if kind == "visit_soon" and record:
        return {"label": "Your follow-up visit, " + str(record.get("due_date")), "record": source,
                "citation": _citation(service, identity, record)}
    if kind == "missed_task" and record:
        task = service.storage.get(identity.patient, record.get("task_id")) if record.get("task_id") else None
        return {"label": f"{record.get('task_label') or 'A task'} was due", "when": record.get("due_at"), "record": source,
                "citation": _citation(service, identity, task)}
    if kind == "no_checkin" and record:
        return {"label": "Your last check-in", "when": record.get("observed_at"), "record": source}
    if kind == "teach_back_due" and record:
        return {"label": "From your approved plan", "record": source, "citation": _citation(service, identity, record)}
    return {"label": "Plan items from your documents that you haven't reviewed yet"}


def _recorded_by(service: Any, identity: Any, row: dict[str, Any]) -> str:
    actor = row.get("actor_id")
    if actor == identity.patient:
        return "you"
    return service._display_name(identity.patient, actor) if actor else "unknown"


def _teach_back_view(service: Any, identity: Any) -> dict[str, Any]:
    """Each checkable value of the plan: its latest result, or not checked yet, with its document lines."""
    from ..teach_back import expected_for, question_for
    results = {(r["item_id"], r["check"]): r for r in service.teach_back_results(identity)}
    rows = []
    for entry in service.teach_back_checks(identity):
        item, check = entry["item"], entry["check"]
        result = results.get((item["id"], check))
        rows.append({"item_id": item["id"], "check": check, "label": item.get("label"), "question": question_for(item, check),
                     "expected": expected_for(item, check), "result": result["result"] if result else "not_checked",
                     "heard": result.get("heard") if result else None, "asked_at": result.get("asked_at") if result else None,
                     "citation": _citation(service, identity, item)})
    return {"checks": rows}


def view_details(deps: Any, identity: Any, view: str, record_ids: list[str]) -> Any:
    """Return the detail for one view, using only scope-checked service calls."""
    service = deps.service
    if view in {"plan-review", "tasks"}:
        items = sorted(service.list_care_tasks(identity), key=_document_order)
        data: dict[str, Any] = {"items": _with_citations(deps, identity, items)}
        if view == "tasks" and identity.role == "patient":
            data["suggestions"] = [{"kind": s["kind"], "say": s["say"], "because": _because(service, identity, s)}
                                   for s in service.suggestions(identity)]
        if view == "plan-review" and identity.role == "patient":
            jobs = service.intake_jobs(identity)
            if jobs:
                job = jobs[0]
                data["document"] = {k: job.get(k) for k in ("id", "title", "status", "error", "counts", "notes",
                                                            "unused_lines", "follow_up_date", "pages", "engine")}
        return data
    if view == "plan-source":
        if record_ids:
            return {"sources": [service.source_excerpt(identity, record_ids[0])]}
        items = service.list_care_tasks(identity)
        source_ids = list(dict.fromkeys(i["source_id"] for i in items if i.get("source_id")))
        return {"sources": [service.source_excerpt(identity, s) for s in source_ids]}
    if view == "care-circle":
        now = int(service.clock())
        from ..core import ACCESS_PHRASES
        access = [{"name": person["name"], "last_at": person.get("last_at"),
                   "actions": [f"{ACCESS_PHRASES[action]}{'' if n == 1 else f' ({n} times)'}"
                               for action, n in person["actions"].items()]}
                  for person in service.access_summary(identity, now - 7 * 86_400, now)]
        return {"grants": service.list_grants(identity), "access": access}
    if view == "notifications":
        return {"updates": service.notifications(identity)}
    if view == "records":
        return {"records": service.list_records(identity)}
    if view == "history":
        wanted = set(record_ids)
        return {"records": [r for r in service.list_records(identity) if r["id"] in wanted]}
    if view == "check-in-trend":
        try:
            rules = _active_rules(service.list_care_tasks(identity))
        except AccessDenied:
            rules = []
        observations = service.list_observations(identity)
        data = {"observations": observations, "thresholds": _rule_thresholds(rules)}
        if identity.role == "patient":  # who recorded each value, and the rule's own words and lines; a family member sees only the chart
            data["observations"] = [dict(o) | {"recorded_by": _recorded_by(service, identity, o)} for o in observations]
            data["rules"] = [{"threshold": r["rule_spec"]["threshold"], "consecutive_days": r["rule_spec"]["consecutive_days"],
                              "text": r.get("text"), "citation": _citation(service, identity, r)} for r in rules]
        return data
    if view == "visit-handoff":
        if identity.role != "patient":
            raise AccessDenied()
        handoffs = service.storage.list(identity.patient, "HANDOFF")
        if record_ids:
            handoffs = [h for h in handoffs if h["id"] == record_ids[0]]
        if not handoffs:
            raise AccessDenied()
        return {"handoff": max(handoffs, key=lambda h: h.get("created_at", 0))}
    if view == "teach-back":
        return _teach_back_view(service, identity)
    if view == "export":
        return service.export(identity)
    raise AccessDenied()


def app_html(view: str) -> str:
    template = files(__package__).joinpath("app.html").read_text(encoding="utf-8")
    return template.replace("__CARELOOP_VIEW__", view).replace("__CARELOOP_TITLE__", VIEWS[view])


def register(mcp: MCPServer, deps: Any) -> None:
    """Register one static MCP App resource per view advertised in tool ``_meta``."""
    def shell_for(view: str):
        def shell() -> str:
            return app_html(view)
        return shell

    for view, title in VIEWS.items():
        shell = shell_for(view)
        mcp.resource(
            f"ui://careloop/{view}",
            name=f"careloop-{view}",
            title=f"CareLoop {title}",
            description="CareLoop MCP App view. Data loads only through the authenticated app-only tool.",
            mime_type=MIME,
        )(shell)
