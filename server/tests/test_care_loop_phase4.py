"""Phase 4 deterministic observation, rule, and handoff contracts."""
from __future__ import annotations

import pytest

from care_loop.auth import Identity
from care_loop.core import AccessDenied, CareLoopService
from care_loop.storage import CareLoopStorage


def patient() -> Identity:
    return Identity("patient", "patient", "patient")


def service(now: list[int]) -> CareLoopService:
    return CareLoopService(CareLoopStorage(":memory:", clock=lambda: now[0]), clock=lambda: now[0])


def active_rule(svc: CareLoopService) -> dict:
    doc = svc.create_document(patient(), "Synthetic plan", [{"page": 1, "excerpt": "RULE: PAIN_SCORE_AT_OR_ABOVE threshold=7 consecutive_days=2"}], reviewed=True)
    draft = svc.create_plan_rule(patient(), "Pain follow-up", {"kind": "pain_score_at_or_above", "threshold": 7, "consecutive_days": 2}, source_id=doc["id"])
    return svc.approve_plan_item(patient(), draft["id"])


def test_rule_requires_exact_reviewed_source_grammar() -> None:
    now = [1_700_000_000]; svc = service(now)
    doc = svc.create_document(patient(), "Synthetic plan", [{"page": 1, "excerpt": "RULE: PAIN_SCORE_AT_OR_ABOVE threshold=7 consecutive_days=2"}], reviewed=True)
    with pytest.raises(ValueError, match="exactly match"):
        svc.create_plan_rule(patient(), "Pain follow-up", {"kind": "pain_score_at_or_above", "threshold": 8, "consecutive_days": 2}, source_id=doc["id"])
    draft = svc.create_plan_rule(patient(), "Different display text", {"kind": "pain_score_at_or_above", "threshold": 7, "consecutive_days": 2}, source_id=doc["id"])
    assert svc.approve_plan_item(patient(), draft["id"])["status"] == "active"


def test_observation_boundaries_retry_and_immutable_correction() -> None:
    now = [1_700_000_000]; svc = service(now)
    low = svc.record_observation(patient(), pain_score=0, observed_at=now[0], idempotency_key="a")
    high = svc.record_observation(patient(), pain_score=10, observed_at=now[0], idempotency_key="b")
    assert svc.record_observation(patient(), pain_score=10, observed_at=now[0], idempotency_key="b")["id"] == high["id"]
    with pytest.raises(ValueError): svc.record_observation(patient(), pain_score=11, idempotency_key="x")
    with pytest.raises(ValueError): svc.record_observation(patient(), pain_score=9, observed_at=now[0], idempotency_key="b")
    corrected = svc.record_observation(patient(), pain_score=4, observed_at=now[0], idempotency_key="c", corrects_id=high["id"])
    assert svc.storage.get("patient", high["id"])["pain_score"] == 10
    assert {row["id"] for row in svc.list_observations(patient())} == {low["id"], corrected["id"]}


def test_rule_has_one_alert_per_episode_and_explicit_delivery_failure() -> None:
    now = [1_700_000_000]; svc = service(now); active_rule(svc)
    day = 86_400
    svc.record_observation(patient(), pain_score=7, observed_at=now[0] - day, idempotency_key="one")
    svc.record_observation(patient(), pain_score=7, observed_at=now[0], idempotency_key="two")
    alerts = svc.storage.list("patient", "ALERT")
    assert len(alerts) == 1 and alerts[0]["delivery_status"] == "failed"
    svc.record_observation(patient(), pain_score=8, observed_at=now[0], idempotency_key="three")
    assert len(svc.storage.list("patient", "ALERT")) == 1
    # A low day closes the episode; the next two days form exactly one new one.
    now[0] += day; svc.record_observation(patient(), pain_score=0, observed_at=now[0], idempotency_key="four")
    now[0] += day; svc.record_observation(patient(), pain_score=7, observed_at=now[0], idempotency_key="five")
    now[0] += day; svc.record_observation(patient(), pain_score=7, observed_at=now[0], idempotency_key="six")
    assert len(svc.storage.list("patient", "ALERT")) == 2


def test_correction_invalidates_alert_when_qualifying_episode_is_removed() -> None:
    now = [1_700_000_000]; svc = service(now); active_rule(svc)
    day = 86_400
    caregiver = Identity("caregiver", "caregiver", "patient")
    svc.grant(patient(), "caregiver", ["receive_alerts", "acknowledge_alerts"])
    svc.record_observation(patient(), pain_score=7, observed_at=now[0] - day, idempotency_key="one")
    high = svc.record_observation(patient(), pain_score=7, observed_at=now[0], idempotency_key="two")
    alert = svc.storage.list("patient", "ALERT")[0]
    svc.record_observation(patient(), pain_score=2, observed_at=now[0], idempotency_key="fix", corrects_id=high["id"])
    invalidated = svc.storage.get("patient", alert["id"])
    assert invalidated["status"] == "invalidated"
    assert svc.notifications(caregiver) == []
    with pytest.raises(AccessDenied):
        svc.acknowledge_alert(caregiver, alert["id"])
    handoff = svc.create_visit_handoff(patient(), now[0] - day, now[0])
    assert handoff["alerts"] == []


def test_caregiver_observation_write_needs_explicit_scope_and_revocation() -> None:
    now = [1000]; svc = service(now); caregiver = Identity("caregiver", "caregiver", "patient")
    with pytest.raises(AccessDenied): svc.record_observation(caregiver, pain_score=2, idempotency_key="x")
    svc.grant(patient(), "caregiver", ["write_observations"])
    assert svc.record_observation(caregiver, pain_score=2, idempotency_key="x")["actor_id"] == "caregiver"
    svc.revoke(patient(), "caregiver")
    with pytest.raises(AccessDenied): svc.record_observation(caregiver, pain_score=2, idempotency_key="y")


def test_restart_preserves_idempotency_and_handoff_is_date_bounded_source_cited(tmp_path) -> None:
    now = [1_700_000_000]; path = tmp_path / "phase4.db"
    first = CareLoopService(CareLoopStorage(path, clock=lambda: now[0]), clock=lambda: now[0])
    rule = active_rule(first)
    observation = first.record_observation(patient(), pain_score=5, observed_at=now[0], idempotency_key="stable")
    first.storage.close()
    second = CareLoopService(CareLoopStorage(path, clock=lambda: now[0]), clock=lambda: now[0])
    assert second.record_observation(patient(), pain_score=5, observed_at=now[0], idempotency_key="stable")["id"] == observation["id"]
    handoff = second.create_visit_handoff(patient(), now[0], now[0])
    assert handoff["totals"]["observations"] == 1
    assert handoff["plan_items"][0]["plan_id"] == rule["id"]
    assert handoff["plan_items"][0]["source_citation"]["source_id"] == rule["source_id"]
    assert handoff["plan_items"][0]["status"] == "active"
    assert handoff["label"].startswith("Patient-generated")
    second.storage.close()
