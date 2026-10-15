"""Standalone, sanitized CareLoop evaluation harness.

Each execution creates a new SQLite file, fixed clock, and credential-derived
persona map.  It does not import application simulators or preserve state
between cases.  Reports retain only evaluation metadata and tool names.
"""
from __future__ import annotations

import json
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from care_loop.auth import AuthError, TokenAuth
from care_loop.core import AccessDenied, CareLoopService

from .agent import CareSimAgent
from .config import FixedClock, personas
from .hub import create_service


ALLOWED_TOOLS = frozenset({
    "list_care_tasks", "record_task_completion", "get_care_plan_source",
    "record_observation", "search_care_history", "create_visit_handoff",
    "list_generic_notifications", "acknowledge_alert",
})
CASE_FIELDS = frozenset({
    "id", "category", "baseline", "actor", "setup", "say", "turns",
    "expected_tools", "forbidden_tools", "reply_contains", "max_calls",
    "state_assertions",
})


@dataclass
class ToolCall:
    name: str
    ok: bool


@dataclass
class EvalResult:
    id: str
    category: str
    passed: bool
    problems: list[str]
    calls: list[ToolCall]
    seconds: float
    run: int = 1

    def safe_json(self) -> dict[str, Any]:
        return asdict(self)


def load_cases(path: str | Path) -> list[dict[str, Any]]:
    """Load and validate declarative cases before any service is constructed."""

    raw = json.loads(Path(path).read_text())
    if not isinstance(raw, list):
        raise ValueError("CareLoop cases must be a JSON array")
    seen: set[str] = set()
    for case in raw:
        if not isinstance(case, dict) or set(case) - CASE_FIELDS:
            raise ValueError("unknown or invalid CareLoop eval case field")
        required = {"id", "category", "baseline", "actor"}
        if not required <= set(case) or not all(isinstance(case[x], str) and case[x] for x in required):
            raise ValueError("each case needs id, category, baseline, and actor")
        if case["id"] in seen:
            raise ValueError("CareLoop eval case ids must be unique")
        seen.add(case["id"])
        if case["actor"] not in personas():
            raise ValueError("case has an unknown authenticated persona")
        for field in ("setup", "expected_tools", "forbidden_tools", "reply_contains", "state_assertions"):
            if field in case and (not isinstance(case[field], list) or not all(isinstance(x, str) for x in case[field])):
                raise ValueError(f"case field {field} must be an array of strings")
        turns = case.get("turns", [case["say"]] if "say" in case else [])
        if not isinstance(turns, list) or not all(isinstance(x, str) for x in turns):
            raise ValueError("case turns must be strings")
        if "say" in case and "turns" in case:
            raise ValueError("use say or turns, not both")
        for name in case.get("expected_tools", []) + case.get("forbidden_tools", []):
            if name not in ALLOWED_TOOLS:
                raise ValueError(f"unknown CareLoop eval tool: {name}")
        if not isinstance(case.get("max_calls", len(turns)), int) or case.get("max_calls", len(turns)) < 0:
            raise ValueError("max_calls must be a non-negative integer")
    return raw


class CareEvalHarness:
    """An isolated fixture world and closed tool dispatcher for one case."""

    def __init__(self, database: Path) -> None:
        self.clock = FixedClock()
        self.people = personas()
        self.service: CareLoopService = create_service(database, self.clock)
        self.agent = CareSimAgent()
        self.calls: list[ToolCall] = []
        self.task_id: str | None = None
        self.source_id: str | None = None
        self.alert_id: str | None = None

    @property
    def patient(self):
        return self.people["patient"]

    def close(self) -> None:
        self.service.storage.close()

    def setup(self, names: list[str]) -> None:
        allowed = {
            "approved_plan", "draft_plan", "grant_tasks", "grant_observations",
            "grant_alerts", "grant_acknowledgement", "rule_episode", "corrected_episode",
            "other_patient_data", "expired_alert_grant", "revoked_alert_grant", "deleted_task",
        }
        unknown = set(names) - allowed
        if unknown:
            raise ValueError(f"unknown CareLoop eval setup: {sorted(unknown)}")
        for name in names:
            getattr(self, f"_setup_{name}")()

    def _ensure_plan(self) -> None:
        if self.task_id:
            return
        document = self.service.create_document(
            self.patient, "Synthetic approved plan",
            [{"page": 1, "excerpt": "TASK: Complete the synthetic checklist"},
             {"page": 1, "excerpt": "RULE: PAIN_SCORE_AT_OR_ABOVE threshold=7 consecutive_days=2"}],
            reviewed=True,
        )
        task = self.service.write(self.patient, "PLAN_TASK", {
            "text": "Complete the synthetic checklist", "status": "active", "approval_required": False,
        }, source_id=document["id"], reviewed=True)
        rule = self.service.create_plan_rule(self.patient, "Approved follow-up rule", {
            "kind": "pain_score_at_or_above", "threshold": 7, "consecutive_days": 2,
        }, source_id=document["id"])
        self.service.approve_plan_item(self.patient, rule["id"])
        self.task_id, self.source_id = task["id"], document["id"]

    def _setup_approved_plan(self) -> None:
        self._ensure_plan()

    def _setup_draft_plan(self) -> None:
        if not self.source_id:
            document = self.service.create_document(self.patient, "Synthetic source", [{"page": 1, "excerpt": "TASK: Draft"}], reviewed=True)
            self.source_id = document["id"]
        self.service.write(self.patient, "PLAN_TASK", {"text": "Draft synthetic task", "status": "draft", "approval_required": True}, source_id=self.source_id, reviewed=False)

    def _setup_grant_tasks(self) -> None:
        self.service.grant(self.patient, self.people["caregiver"].subject_id, ["read_tasks"])

    def _setup_grant_observations(self) -> None:
        self.service.grant(self.patient, self.people["caregiver"].subject_id, ["read_observations", "write_observations"])

    def _setup_grant_alerts(self) -> None:
        self.service.grant(self.patient, self.people["caregiver"].subject_id, ["receive_alerts"])

    def _setup_grant_acknowledgement(self) -> None:
        self.service.grant(self.patient, self.people["caregiver"].subject_id, ["acknowledge_alerts"])

    def _setup_rule_episode(self) -> None:
        self._ensure_plan()
        day = 86_400
        self.service.record_observation(self.patient, pain_score=7, observed_at=self.clock.value - day, idempotency_key="fixture-day-one")
        self.service.record_observation(self.patient, pain_score=7, observed_at=self.clock.value, idempotency_key="fixture-day-two")
        self.alert_id = self.service.storage.list(self.patient.patient, "ALERT")[0]["id"]

    def _setup_corrected_episode(self) -> None:
        self._setup_rule_episode()
        rows = self.service.list_observations(self.patient)
        self.service.record_observation(self.patient, pain_score=2, observed_at=self.clock.value, idempotency_key="fixture-correction", corrects_id=rows[-1]["id"])

    def _setup_other_patient_data(self) -> None:
        self.service.write(self.people["other_patient"], "PLAN_TASK", {"text": "Other synthetic checklist", "status": "active"})

    def _setup_expired_alert_grant(self) -> None:
        self.service.grant(self.patient, self.people["caregiver"].subject_id, ["receive_alerts"], self.clock.value + 1)
        self.clock.advance(1)

    def _setup_revoked_alert_grant(self) -> None:
        self.service.grant(self.patient, self.people["caregiver"].subject_id, ["receive_alerts"])
        self.service.revoke(self.patient, self.people["caregiver"].subject_id)

    def _setup_deleted_task(self) -> None:
        self._ensure_plan()
        assert self.task_id
        self.service.delete(self.patient, self.task_id)

    def turn(self, actor: str, utterance: str) -> str:
        plan = self.agent.turn(utterance)
        if plan.tool is None:
            return plan.reply
        ok = True
        try:
            self._dispatch(actor, plan.tool)
        except (AccessDenied, ValueError, KeyError):
            ok = False
        self.calls.append(ToolCall(plan.tool, ok))
        return plan.reply

    def _dispatch(self, actor: str, tool: str) -> None:
        identity = self.people[actor]
        if tool == "list_care_tasks":
            self.service.list_care_tasks(identity)
        elif tool == "record_task_completion":
            if not self.task_id:
                raise ValueError("no task fixture")
            self.service.record_task_completion(identity, self.task_id)
        elif tool == "get_care_plan_source":
            if not self.source_id:
                raise ValueError("no source fixture")
            self.service.source_excerpt(identity, self.source_id)
        elif tool == "record_observation":
            self.service.record_observation(identity, pain_score=4, idempotency_key=f"eval-{len(self.calls)}")
        elif tool == "search_care_history":
            self.service.search(identity, "synthetic")
        elif tool == "create_visit_handoff":
            self.service.create_visit_handoff(identity, self.clock.value - 3 * 86_400, self.clock.value)
        elif tool == "list_generic_notifications":
            self.service.notifications(identity)
        elif tool == "acknowledge_alert":
            if not self.alert_id:
                raise ValueError("no alert fixture")
            self.service.acknowledge_alert(identity, self.alert_id)
        else:  # validation makes this unreachable
            raise ValueError("unknown tool")

    def assert_state(self, name: str, actor: str) -> None:
        caregiver = self.people["caregiver"]
        if name == "auth_rejected":
            try:
                TokenAuth({"known": self.patient}).identity_for_headers({"Authorization": "Bearer wrong"})
            except AuthError:
                return
            raise AssertionError("invalid credential was accepted")
        if name == "cross_patient_isolated":
            self._setup_other_patient_data()
            assert self.service.search(self.patient, "Other") == []
            return
        if name == "drafts_hidden_from_caregiver":
            assert all(row.get("status") == "active" for row in self.service.list_care_tasks(caregiver))
            return
        if name == "scope_denies_documents":
            try:
                self.service.list_records(caregiver, "DOCUMENT")
            except AccessDenied:
                return
            raise AssertionError("document scope was granted")
        if name == "source_is_linked_and_reviewed":
            assert self.source_id and self.service.source_excerpt(caregiver, self.source_id)["source_id"] == self.source_id
            return
        if name == "revocation_denied":
            try:
                self.service.notifications(caregiver)
            except AccessDenied:
                return
            raise AssertionError("revoked caregiver retained notification access")
        if name == "expiry_denied":
            try:
                self.service.notifications(caregiver)
            except AccessDenied:
                return
            raise AssertionError("expired caregiver retained notification access")
        if name == "notifications_generic":
            notices = self.service.notifications(caregiver)
            assert notices and all(set(row) == {"case_id", "status"} and row["status"] in {"action_required", "acknowledged"} for row in notices)
            return
        if name == "audit_closed_vocabulary":
            try:
                self.service.audit(self.patient, "unbounded text", "unbounded text")
            except ValueError:
                pass
            else:
                raise AssertionError("audit accepted arbitrary metadata")
            record = self.service.audit(self.patient, "data_exported", "success")
            assert set(record) >= {"action", "outcome"}
            return
        if name == "deleted_records_not_searchable":
            # The approved source can legitimately contain the same generic
            # keyword; assert that the deleted *record* itself is absent.
            assert self.task_id
            assert all(row["id"] != self.task_id for row in self.service.search(self.patient, "checklist"))
            return
        if name == "observation_idempotent_and_bounded":
            first = self.service.record_observation(self.patient, pain_score=0, observed_at=self.clock.value, idempotency_key="assert-idempotent")
            second = self.service.record_observation(self.patient, pain_score=0, observed_at=self.clock.value, idempotency_key="assert-idempotent")
            assert first["id"] == second["id"]
            try:
                self.service.record_observation(self.patient, pain_score=11, idempotency_key="bad-observation")
            except ValueError:
                return
            raise AssertionError("out-of-range observation was accepted")
        if name == "one_alert_per_episode":
            assert len(self.service.storage.list(self.patient.patient, "ALERT")) == 1
            return
        if name == "delivery_failure_visible":
            assert self.alert_id
            assert self.service.storage.get(self.patient.patient, self.alert_id)["delivery_status"] == "failed"
            return
        if name == "handoff_cited_and_bounded":
            handoff = self.service.create_visit_handoff(self.patient, self.clock.value - 86_400, self.clock.value)
            assert handoff["totals"]["observations"] == 2
            assert handoff["plan_items"] and handoff["plan_items"][0]["source_citation"]
            return
        if name == "correction_excludes_stale_evidence":
            assert self.service.list_observations(self.patient)[-1]["pain_score"] == 2
            assert not self.service.storage.list(self.patient.patient, "ALERT")[-1].get("status") == "active"
            return
        if name == "handoff_patient_only":
            try:
                self.service.create_visit_handoff(caregiver, self.clock.value - 1, self.clock.value)
            except AccessDenied:
                return
            raise AssertionError("caregiver could create a handoff")
        raise ValueError(f"unknown CareLoop state assertion: {name}")


def run_case(case: dict[str, Any], run_number: int = 1) -> EvalResult:
    started = time.monotonic()
    problems: list[str] = []
    with tempfile.TemporaryDirectory(prefix="careloop-eval-") as directory:
        harness = CareEvalHarness(Path(directory) / "case.db")
        try:
            harness.setup(case.get("setup", []))
            replies = [harness.turn(case["actor"], text) for text in case.get("turns", [case["say"]] if "say" in case else [])]
            names = [call.name for call in harness.calls]
            for expected in case.get("expected_tools", []):
                if expected not in names:
                    problems.append(f"expected tool not called: {expected}")
            for forbidden in case.get("forbidden_tools", []):
                if forbidden in names:
                    problems.append(f"forbidden tool called: {forbidden}")
            if len(harness.calls) > case.get("max_calls", len(replies)):
                problems.append("maximum tool calls exceeded")
            reply_text = " ".join(replies).lower()
            for expected in case.get("reply_contains", []):
                if expected.lower() not in reply_text:
                    problems.append("reply check failed")
            for assertion in case.get("state_assertions", []):
                try:
                    harness.assert_state(assertion, case["actor"])
                except (AssertionError, AccessDenied, ValueError, KeyError) as exc:
                    problems.append(f"state assertion failed: {assertion} ({type(exc).__name__})")
        except (AccessDenied, ValueError, KeyError) as exc:
            problems.append(f"fixture execution failed: {type(exc).__name__}")
        finally:
            calls = list(harness.calls)
            harness.close()
    return EvalResult(case["id"], case["category"], not problems, problems, calls, round(time.monotonic() - started, 4), run_number)


def run(cases: list[dict[str, Any]], repeat: int = 1) -> dict[str, Any]:
    results = [run_case(case, number) for number in range(1, repeat + 1) for case in cases]
    by_id: dict[str, list[EvalResult]] = {}
    for result in results:
        by_id.setdefault(result.id, []).append(result)
    always_pass = sorted(case_id for case_id, rows in by_id.items() if all(row.passed for row in rows))
    never_pass = sorted(case_id for case_id, rows in by_id.items() if not any(row.passed for row in rows))
    flaky = sorted(case_id for case_id, rows in by_id.items() if any(row.passed for row in rows) and not all(row.passed for row in rows))
    categories: dict[str, dict[str, int]] = {}
    for result in results:
        bucket = categories.setdefault(result.category, {"passed": 0, "cases": 0})
        bucket["cases"] += 1
        bucket["passed"] += int(result.passed)
    return {
        "format": "careloop-eval-report-v1", "model": "deterministic-mock", "results": [result.safe_json() for result in results],
        "summary": {"cases": len(results), "passed": sum(row.passed for row in results), "errors": sum(not row.passed for row in results),
                    "runs": repeat, "always_pass": always_pass, "flaky": flaky, "never_pass": never_pass, "by_category": categories},
    }


def compare(current: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    """Compare only pass state by case ID; no sensitive payload is retained."""

    def state(report: dict[str, Any]) -> dict[str, bool]:
        grouped: dict[str, list[bool]] = {}
        for result in report.get("results", []):
            grouped.setdefault(result["id"], []).append(bool(result["passed"]))
        return {case_id: all(values) for case_id, values in grouped.items()}
    before, after = state(baseline), state(current)
    lines = []
    for case_id in sorted(set(before) | set(after)):
        if before.get(case_id) != after.get(case_id):
            lines.append(f"{case_id}: {'pass' if before.get(case_id) else 'fail'} -> {'pass' if after.get(case_id) else 'fail'}")
    return lines or ["No pass-state changes from baseline."]
