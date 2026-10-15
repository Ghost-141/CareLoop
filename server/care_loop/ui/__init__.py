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
    "export": "Data export",
}


def _with_citations(deps: Any, identity: Any, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cache: dict[str, Any] = {}
    rows = []
    for item in items:
        row = dict(item)
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


def _rule_thresholds(items: list[dict[str, Any]]) -> list[int]:
    return sorted({item["rule_spec"]["threshold"] for item in items
                   if item["type"] == "PLAN_RULE" and item.get("status") == "active" and item.get("rule_spec")})


def view_details(deps: Any, identity: Any, view: str, record_ids: list[str]) -> Any:
    """Return the detail for one view, using only scope-checked service calls."""
    service = deps.service
    if view in {"plan-review", "tasks"}:
        return {"items": _with_citations(deps, identity, service.list_care_tasks(identity))}
    if view == "plan-source":
        if record_ids:
            return {"sources": [service.source_excerpt(identity, record_ids[0])]}
        items = service.list_care_tasks(identity)
        source_ids = list(dict.fromkeys(i["source_id"] for i in items if i.get("source_id")))
        return {"sources": [service.source_excerpt(identity, s) for s in source_ids]}
    if view == "care-circle":
        return {"grants": service.list_grants(identity)}
    if view == "notifications":
        return {"updates": service.notifications(identity)}
    if view == "records":
        return {"records": service.list_records(identity)}
    if view == "history":
        wanted = set(record_ids)
        return {"records": [r for r in service.list_records(identity) if r["id"] in wanted]}
    if view == "check-in-trend":
        try:
            thresholds = _rule_thresholds(service.list_care_tasks(identity))
        except AccessDenied:
            thresholds = []
        return {"observations": service.list_observations(identity), "thresholds": thresholds}
    if view == "visit-handoff":
        if identity.role != "patient":
            raise AccessDenied()
        handoffs = service.storage.list(identity.patient, "HANDOFF")
        if record_ids:
            handoffs = [h for h in handoffs if h["id"] == record_ids[0]]
        if not handoffs:
            raise AccessDenied()
        return {"handoff": max(handoffs, key=lambda h: h.get("created_at", 0))}
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
