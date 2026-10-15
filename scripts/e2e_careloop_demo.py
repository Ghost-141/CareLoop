#!/usr/bin/env python3
"""Run CareLoop's synthetic, private API journey end to end.

This script deliberately drives the real CareLoop ASGI application with an
in-process HTTP client.  It creates a temporary SQLite database and fixed
synthetic identities, so it neither starts a server nor reads local CareLoop
data.  The report contains step names and pass/fail metadata only--never
credentials, record identifiers, source excerpts, or observation values.

    uv run python scripts/e2e_careloop_demo.py
    uv run python scripts/e2e_careloop_demo.py --out /tmp/careloop-demo
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# ``uv run python scripts/...`` does not add the repository's server package
# directory when the project is not installed editable.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "server") not in sys.path:
    sys.path.insert(0, str(ROOT / "server"))

from fastapi.testclient import TestClient

from care_loop.auth import Identity, TokenAuth
from care_loop.config import Settings
from care_loop.server import build_deps, create_app
from care_loop.storage import CareLoopStorage


PATIENT_TOKEN = "synthetic-patient-token"
CAREGIVER_TOKEN = "synthetic-caregiver-token"
START = 1_700_000_000
DAY = 86_400


@dataclass
class Step:
    name: str
    passed: bool = True
    checks: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def require(self, condition: bool, check: str) -> None:
        if condition:
            self.checks.append(check)
        else:
            self.passed = False
            self.problems.append(check)


class Demo:
    """Small, fail-soft driver so all failed assertions reach the report."""

    def __init__(self, db_path: Path) -> None:
        self.now = [START]
        self.auth = TokenAuth({
            PATIENT_TOKEN: Identity("synthetic-patient", "patient", "synthetic-patient"),
            CAREGIVER_TOKEN: Identity("synthetic-caregiver", "caregiver", "synthetic-patient"),
        })
        self.storage = CareLoopStorage(db_path, clock=lambda: self.now[0])
        self.deps = build_deps(
            Settings(db_path=str(db_path), patient_id="synthetic-patient"),
            storage=self.storage,
            auth=self.auth,
            clock=lambda: self.now[0],
        )
        self.client = TestClient(create_app(self.deps), base_url="http://127.0.0.1:8010")
        self.client.__enter__()
        self.steps: list[Step] = []

    def headers(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def step(self, name: str) -> Step:
        item = Step(name)
        self.steps.append(item)
        return item

    @staticmethod
    def _json(response: Any) -> dict[str, Any]:
        try:
            return response.json()
        except Exception:
            return {}

    def run(self) -> None:
        # Browser-style shell and empty/unauthenticated states use the actual
        # private portal routes. The workflow itself is API driven until a
        # richer dashboard exists.
        step = self.step("private portal states")
        portal = self.client.get("/care")
        # These structural markers survive dashboard copy changes while
        # proving the real private sign-in shell and authenticated dashboard
        # navigation are present.
        dashboard_markers = (
            'id="signin-form"',
            'id="app"',
            'aria-label="CareLoop views"',
        )
        step.require(
            portal.status_code == 200 and all(marker in portal.text for marker in dashboard_markers),
            "private dashboard shell loads",
        )
        empty = self.client.get("/api/care/tasks", headers=self.headers(PATIENT_TOKEN))
        step.require(empty.status_code == 200 and self._json(empty).get("tasks") == [], "new patient has an empty task list")
        anonymous = self.client.get("/api/care/me")
        step.require(anonymous.status_code == 401, "unauthenticated private API is denied")

        step = self.step("authenticated MCP transport")
        initialized = self.client.post("/mcp", headers={
            **self.headers(PATIENT_TOKEN),
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }, json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                       "clientInfo": {"name": "careloop-e2e", "version": "1"}},
        })
        step.require(initialized.status_code == 200 and '"serverInfo"' in initialized.text,
                     "authenticated MCP transport initializes")

        step = self.step("upload synthetic plan")
        fixture = "\n".join((
            "TASK: Complete the first synthetic activity | schedule: morning",
            "TASK: Complete the second synthetic activity | schedule: evening",
            "RULE: PAIN_SCORE_AT_OR_ABOVE threshold=7 consecutive_days=2",
        ))
        response = self.client.post("/api/care/documents/text", headers=self.headers(PATIENT_TOKEN), json={"title": "Synthetic plan", "text": fixture})
        body = self._json(response)
        drafts = body.get("intake", {}).get("drafts", [])
        step.require(response.status_code == 200, "synthetic plan accepted")
        step.require(len(drafts) == 3 and all(item.get("status") == "draft" for item in drafts), "all plan items remain drafts")
        self.draft_ids = [item.get("id", "") for item in drafts]

        step = self.step("patient approves plan")
        approvals = [self.client.post(f"/api/care/plan/{record_id}/approve", headers=self.headers(PATIENT_TOKEN)) for record_id in self.draft_ids]
        step.require(len(approvals) == 3 and all(response.status_code == 200 for response in approvals), "two tasks and one rule are approved")
        tasks = self.client.get("/api/care/tasks", headers=self.headers(PATIENT_TOKEN))
        step.require(tasks.status_code == 200 and len(self._json(tasks).get("tasks", [])) == 3, "approved plan is available to patient")

        step = self.step("grant scoped caregiver access")
        invitation = self.client.post("/api/care/invitations", headers=self.headers(PATIENT_TOKEN), json={"scopes": ["read_tasks", "receive_alerts", "acknowledge_alerts"]})
        invitation_id = self._json(invitation).get("invitation", {}).get("id", "")
        accepted = self.client.post(f"/api/care/invitations/{invitation_id}/accept", headers=self.headers(CAREGIVER_TOKEN))
        step.require(invitation.status_code == 200 and accepted.status_code == 200, "authenticated caregiver accepts narrow grant")
        records = self.client.get("/api/care/records?record_type=OBSERVATION", headers=self.headers(CAREGIVER_TOKEN))
        step.require(records.status_code == 403, "caregiver lacks observation-reading scope")
        self.invitation_id = invitation_id

        step = self.step("record synthetic observations")
        # Fixed UTC timestamps avoid local-time ambiguity. The second and third
        # entries are on consecutive days and meet only the approved rule.
        entries = ((START, 2), (START + DAY, 7), (START + 2 * DAY, 7))
        responses = []
        for index, (when, value) in enumerate(entries, start=1):
            self.now[0] = when
            responses.append(self.client.post("/api/care/observations", headers=self.headers(PATIENT_TOKEN), json={
                "pain_score": value, "observed_at": when, "idempotency_key": f"synthetic-day-{index}",
            }))
        step.require(all(response.status_code == 200 for response in responses), "three observations are recorded with idempotency keys")
        alerts = self.deps.storage.list("synthetic-patient", "ALERT")
        step.require(len(alerts) == 1, "approved deterministic rule creates one alert episode")
        self.alert_id = alerts[0]["id"] if len(alerts) == 1 else ""

        step = self.step("generic notification and acknowledgement")
        notifications = self.client.get("/api/care/notifications", headers=self.headers(CAREGIVER_TOKEN))
        notices = self._json(notifications).get("notifications", [])
        step.require(notifications.status_code == 200 and notices == [{"case_id": self.alert_id, "status": "action_required"}], "caregiver sees generic case/status only")
        # The serialized API response must not contain the detailed record
        # field names or values; it is the shared-style generic surface.
        wire = notifications.text.lower()
        step.require("pain" not in wire and "source" not in wire and "episode" not in wire, "generic surface has no private detail")
        acknowledgement = self.client.post(f"/api/care/alerts/{self.alert_id}/acknowledge", headers=self.headers(CAREGIVER_TOKEN))
        step.require(acknowledgement.status_code == 200 and self._json(acknowledgement).get("acknowledgement", {}).get("status") == "acknowledged", "caregiver acknowledges generic alert")

        step = self.step("create source-linked handoff")
        handoff = self.client.post("/api/care/handoffs", headers=self.headers(PATIENT_TOKEN), json={"from_date": START, "to_date": START + 2 * DAY})
        summary = self._json(handoff).get("handoff", {})
        totals = summary.get("totals", {})
        citations = [item.get("source_citation") for item in summary.get("plan_items", [])]
        step.require(handoff.status_code == 200, "patient can create date-bounded handoff")
        step.require(totals.get("observations") == 3 and totals.get("alerts") == 1, "handoff totals match authoritative records")
        step.require(len(citations) == 3 and all(citation and citation.get("source_id") for citation in citations), "handoff contains plan source citations")

        step = self.step("revoke and deny stale caregiver access")
        revoked = self.client.post(f"/api/care/grants/{self.invitation_id}/revoke", headers=self.headers(PATIENT_TOKEN))
        step.require(revoked.status_code == 200 and self._json(revoked).get("revoked") is True, "patient revokes caregiver grant")
        # Re-request the same endpoints: this models a stale page reload and
        # direct API retry with an existing credential.
        reload = self.client.get("/api/care/notifications", headers=self.headers(CAREGIVER_TOKEN))
        direct = self.client.post(f"/api/care/alerts/{self.alert_id}/acknowledge", headers=self.headers(CAREGIVER_TOKEN))
        step.require(reload.status_code == 403, "stale caregiver notification reload is denied")
        step.require(direct.status_code == 403, "post-revocation direct acknowledgement is denied")

    def close(self) -> None:
        self.client.__exit__(None, None, None)
        self.storage.close()


def write_report(out: Path, steps: list[Step], mode: str) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    report = {
        "demo": "careloop-synthetic-e2e",
        "mode": mode,
        "passed": all(step.passed for step in steps),
        "summary": {"steps": len(steps), "failed": sum(not step.passed for step in steps)},
        "steps": [asdict(step) for step in steps],
        "artifacts": {"trace": "trace.json", "screenshots": []},
    }
    # A separate trace is deliberately just the report's operational metadata.
    # Do not add response bodies, headers, IDs, or timestamps here.
    (out / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "trace.json").write_text(json.dumps({"steps": [{"name": step.name, "passed": step.passed} for step in steps]}, indent=2) + "\n", encoding="utf-8")
    return out / "report.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / ".careloop-e2e", help="directory for sanitized report and trace")
    parser.add_argument("--headed", action="store_true", help="accepted for a future browser dashboard; API checks remain headless")
    parser.add_argument("--video", action="store_true", help="accepted for a future browser dashboard; no video is produced in API mode")
    args = parser.parse_args(argv)
    # TestClient may inherit a verbose application logging setup. The journey
    # report is intentionally sanitized, and its console output should be too.
    logging.disable(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    mode = "api-headless"
    if args.headed or args.video:
        print("Note: the current private portal has no interactive dashboard controls; running verified API mode.")
    with tempfile.TemporaryDirectory(prefix="careloop-e2e-") as temp:
        demo = Demo(Path(temp) / "careloop.db")
        try:
            demo.run()
        finally:
            demo.close()
    report_path = write_report(args.out, demo.steps, mode)
    for step in demo.steps:
        print(f"{'PASS' if step.passed else 'FAIL'}  {step.name}")
        for problem in step.problems:
            print(f"      - {problem}")
    print(f"Sanitized report: {report_path}")
    return 0 if all(step.passed for step in demo.steps) else 1


if __name__ == "__main__":
    raise SystemExit(main())
