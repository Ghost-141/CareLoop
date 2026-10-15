"""Patient-scoped CareLoop record service; source records are authoritative."""
from __future__ import annotations
import hashlib, json, time, uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .auth import Identity
from .storage import CareLoopStorage

CORE_TYPES = {"PATIENT", "DOCUMENT", "PLAN_TASK", "PLAN_RULE", "OBSERVATION", "TASK_EVENT", "CONSENT", "ALERT", "HANDOFF", "SEARCH_ENTRY", "AUDIT"}
SEARCHABLE_TYPES = {"DOCUMENT", "PLAN_TASK", "PLAN_RULE", "OBSERVATION", "TASK_EVENT", "HANDOFF"}
# These are deliberately capability names, not a general-purpose role bag.  A
# caregiver never receives ownership or data-rights capabilities.
CAREGIVER_SCOPES = frozenset({"read_tasks", "read_observations", "write_observations", "receive_alerts", "acknowledge_alerts"})
CAREGIVER_RECORD_TYPES = {
    # Documents and alerts need purpose-built, deliberately minimal views.
    # Never make either full record listable merely because a caregiver needs
    # task context or an alert notification.
    "read_tasks": frozenset({"PLAN_TASK", "PLAN_RULE"}),
    "read_observations": frozenset({"OBSERVATION"}),
}
# Audit fields are intentionally closed vocabulary, so no clinical content can
# be smuggled into logs through caller-controlled action/outcome strings.
AUDIT_ACTIONS = frozenset({"access_invited", "access_granted", "access_revoked", "alert_acknowledged", "data_exported", "record_deleted", "records_purged"})
AUDIT_OUTCOMES = frozenset({"success", "denied", "failed"})

class AccessDenied(PermissionError): pass

@dataclass
class CareLoopService:
    storage: CareLoopStorage
    clock: Any = time.time
    retention_days: int | None = 365
    def __post_init__(self) -> None:
        # Re-evaluate durable approved rules after a restart. Alert episode
        # keys make this safe to run repeatedly.
        for patient in self.storage.patient_ids():
            self.evaluate_rules(patient)
    def _now(self) -> int: return int(self.clock())
    def _id(self) -> str: return uuid.uuid4().hex
    def _day(self, timestamp: int) -> str:
        """Canonical UTC calendar day; CareLoop has no inferred local timezone."""
        return datetime.fromtimestamp(timestamp, UTC).date().isoformat()
    def _fingerprint(self, value: dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    def _require_patient(self, identity: Identity) -> str:
        """Require the data subject, not merely a currently authorized reader."""
        if identity.role != "patient" or identity.subject_id != identity.patient:
            raise AccessDenied("Only the authenticated patient may manage CareLoop data")
        return identity.patient

    def _caregiver_record_types(self, identity: Identity) -> frozenset[str]:
        patient = self.patient_for(identity)
        if identity.role == "patient":
            return frozenset(CORE_TYPES - {"SEARCH_ENTRY", "AUDIT"})
        grants = self.storage.list(patient, "CONSENT")
        types: set[str] = set()
        for grant in grants:
            if (grant.get("accepted_at") and grant.get("caregiver_id") == identity.subject_id and not grant.get("revoked_at")
                    and (not grant.get("expires_at") or grant["expires_at"] > self._now())):
                for scope in grant.get("scopes", []):
                    types.update(CAREGIVER_RECORD_TYPES.get(scope, ()))
        return frozenset(types)
    def patient_for(self, identity: Identity, required_scope: str | None = None) -> str:
        patient=identity.patient
        if identity.role == "patient" and identity.subject_id == patient: return patient
        if identity.role != "caregiver": raise AccessDenied("CareLoop identity has no patient access")
        grants=self.storage.list(patient,"CONSENT")
        valid=any(g.get("accepted_at") and g.get("caregiver_id")==identity.subject_id and not g.get("revoked_at") and (not g.get("expires_at") or g["expires_at"]>self._now()) and (required_scope is None or required_scope in g.get("scopes",[])) for g in grants)
        if not valid: raise AccessDenied("Caregiver access is revoked, expired, or not granted")
        return patient
    def write(self, identity: Identity, record_type: str, data: dict[str, Any], *, source_id: str | None=None, expires_at: int | None=None, reviewed: bool=True) -> dict[str, Any]:
        if record_type not in CORE_TYPES - {"SEARCH_ENTRY", "AUDIT"}: raise ValueError("unsupported CareLoop record type")
        patient=self._require_patient(identity)
        record_id=self._id(); now=self._now()
        item=dict(data) | {"created_at":now,"updated_at":now,"reviewed":reviewed,"source_id":source_id,"actor_id":identity.subject_id}
        if expires_at is None and self.retention_days is not None and record_type != "PATIENT":
            expires_at = now + self.retention_days * 86_400
        saved=self.storage.put(patient,record_id,record_type,item,expires_at=expires_at)
        # Only reviewed source material/patient notes are indexed; values are queried structurally.
        text=saved.get("excerpt") or saved.get("text") or saved.get("title") or ""
        if record_type in SEARCHABLE_TYPES and reviewed and text:
            self.storage.index(patient,record_id,"search-"+record_id,str(text),now)
        return saved
    def create_document(self, identity: Identity, title: str, excerpts: list[dict[str, Any]], source_hash: str | None=None, *, reviewed=False) -> dict[str, Any]:
        if not excerpts: raise ValueError("a document needs at least one page excerpt")
        # Raw PDF bytes/text are intentionally not accepted or retained here.
        normalized=[{"page":int(e["page"]),"excerpt":str(e["excerpt"])} for e in excerpts]
        combined=" ".join(e["excerpt"] for e in normalized)
        return self.write(identity,"DOCUMENT",{"title":title,"source_hash":source_hash or hashlib.sha256(combined.encode()).hexdigest(),"page_excerpts":normalized,"excerpt":combined},reviewed=reviewed)

    def intake_text_document(self, identity: Identity, title: str, text: str) -> dict[str, Any]:
        """Ingest a bounded synthetic text fixture without retaining its raw text.

        Only the short, explicit directive excerpts produced by the local
        parser are stored.  All resulting plan records start as drafts.
        """
        from .intake import extract_text_fixture
        self._require_patient(identity)
        if not title or len(title) > 160:
            raise ValueError("a short document title is required")
        extracted = extract_text_fixture(text)
        # Exact cited snippets are safe to retrieve after approval; the raw
        # request body and all unrelated prose are intentionally discarded.
        document = self.create_document(identity, title, extracted.excerpts or [{"page": 1, "excerpt": "Manual review required"}], extracted.source_hash, reviewed=True)
        document["manual_review_required"] = bool(extracted.manual_review_reasons)
        document["manual_review_reasons"] = extracted.manual_review_reasons
        document = self.storage.put(identity.patient, document["id"], "DOCUMENT", document)
        drafts = []
        conflicting = any("conflicting extracted instructions" in reason for reason in extracted.manual_review_reasons)
        for draft in extracted.drafts:
            payload: dict[str, Any] = {
                "text": draft.text, "page": draft.page,
                # Conflicting instructions are visible as proposals for a
                # human reviewer, but cannot be patient-activated by code.
                "status": "pending_review" if conflicting else "draft",
                "approval_required": True, "manual_review_required": conflicting,
            }
            if draft.schedule is not None:
                payload["schedule"] = draft.schedule
            drafts.append(self.write(identity, "PLAN_TASK" if draft.kind == "TASK" else "PLAN_RULE", payload,
                                     source_id=document["id"], reviewed=False))
        return {"document": document, "drafts": drafts, "manual_review_required": bool(extracted.manual_review_reasons),
                "manual_review_reasons": extracted.manual_review_reasons}

    def approve_plan_item(self, identity: Identity, record_id: str) -> dict[str, Any]:
        """Activate a clinician-cited draft only after the patient confirms it."""
        patient = self._require_patient(identity)
        item = self.storage.get(patient, record_id)
        if not item or item["type"] not in {"PLAN_TASK", "PLAN_RULE"} or item.get("status") != "draft":
            raise ValueError("draft plan item is unavailable")
        if item["type"] == "PLAN_RULE":
            # Unsupported prose may still be displayed as an approved source
            # item, but can never become executable logic.
            spec = self._rule_spec(item)
            if spec is None:
                raise ValueError("rule needs a supported clinician rule specification")
            if not self._source_has_rule_spec(patient, item.get("source_id"), spec):
                raise ValueError("rule needs an exact reviewed source excerpt")
            item["rule_spec"] = spec
        item |= {"status": "active", "reviewed": True, "approval_required": False,
                 "approved_by": identity.subject_id, "approved_at": self._now(), "updated_at": self._now()}
        saved = self.storage.put(patient, record_id, item["type"], item)
        if saved["type"] == "PLAN_RULE": self.evaluate_rules(patient)
        return saved

    def _rule_spec(self, rule: dict[str, Any]) -> dict[str, int] | None:
        """Accept the sole Phase-4 clinician rule grammar.

        A rule must be supplied by reviewed source material as either a
        structured ``rule_spec`` or exact text such as
        ``PAIN_SCORE_AT_OR_ABOVE threshold=7 consecutive_days=2``.  There is
        intentionally no natural-language interpretation or inferred limit.
        """
        raw = rule.get("rule_spec")
        if raw is None:
            import re
            match = re.fullmatch(r"PAIN_SCORE_AT_OR_ABOVE\s+threshold=(\d+)\s+consecutive_days=(\d+)", str(rule.get("text", "")).strip())
            raw = {"kind": "pain_score_at_or_above", "threshold": int(match.group(1)), "consecutive_days": int(match.group(2))} if match else None
        if not isinstance(raw, dict) or set(raw) != {"kind", "threshold", "consecutive_days"} or raw.get("kind") != "pain_score_at_or_above": return None
        threshold, days = raw.get("threshold"), raw.get("consecutive_days")
        if not isinstance(threshold, int) or not isinstance(days, int) or not 0 <= threshold <= 10 or not 1 <= days <= 31: return None
        return {"kind": "pain_score_at_or_above", "threshold": threshold, "consecutive_days": days}

    def _source_rule_specs(self, source: dict[str, Any]) -> list[dict[str, int]]:
        """Parse only the executable rule grammar from reviewed source excerpts.

        Source matching is deliberately exact and local.  It never attempts to
        infer a threshold or duration from prose.
        """
        specs: list[dict[str, int]] = []
        for excerpt in source.get("page_excerpts", []):
            text = str(excerpt.get("excerpt", "")).strip()
            if text.upper().startswith("RULE:"):
                text = text[5:].strip()
            spec = self._rule_spec({"text": text})
            if spec is not None:
                specs.append(spec)
        return specs

    def _source_has_rule_spec(self, patient: str, source_id: str | None, spec: dict[str, int]) -> bool:
        source = self.storage.get(patient, source_id) if source_id else None
        return bool(source and source["type"] == "DOCUMENT" and source.get("reviewed")
                    and any(candidate == spec for candidate in self._source_rule_specs(source)))

    def create_plan_rule(self, identity: Identity, text: str, rule_spec: dict[str, Any], *, source_id: str) -> dict[str, Any]:
        """Create a draft clinician-cited rule; patient approval is still required."""
        patient = self._require_patient(identity)
        source = self.storage.get(patient, source_id)
        spec = self._rule_spec({"rule_spec": rule_spec})
        if not source or source["type"] != "DOCUMENT" or not source.get("reviewed") or spec is None:
            raise ValueError("reviewed source and supported rule are required")
        if not self._source_has_rule_spec(patient, source_id, spec):
            raise ValueError("rule must exactly match a reviewed source excerpt")
        return self.write(identity, "PLAN_RULE", {"text": text, "rule_spec": spec, "status": "draft", "approval_required": True}, source_id=source_id, reviewed=False)

    def _effective_observations(self, patient: str) -> list[dict[str, Any]]:
        rows = self.storage.list(patient, "OBSERVATION")
        replaced = {row.get("corrects_id") for row in rows if row.get("corrects_id")}
        return [row for row in rows if row["id"] not in replaced]

    def record_observation(self, identity: Identity, *, pain_score: int, observed_at: int | None = None,
                           idempotency_key: str, corrects_id: str | None = None) -> dict[str, Any]:
        """Record one synthetic pain score (integer 0..10), preserving corrections as new records."""
        if not idempotency_key or len(idempotency_key) > 128: raise ValueError("idempotency key is required")
        if type(pain_score) is not int or not 0 <= pain_score <= 10: raise ValueError("pain score must be an integer from 0 through 10")
        patient = self.patient_for(identity, "write_observations" if identity.role == "caregiver" else None)
        when = self._now() if observed_at is None else int(observed_at)
        if when < 0 or when > self._now() + 300: raise ValueError("observation timestamp is invalid")
        payload = {"pain_score": pain_score, "unit": "score_0_10", "observed_at": when, "corrects_id": corrects_id}
        fingerprint = self._fingerprint(payload)
        existing = self.storage.idempotency_get(patient, "observation", idempotency_key)
        if existing:
            if existing[1] != fingerprint: raise ValueError("idempotency key was used with different observation data")
            record = self.storage.get(patient, existing[0])
            if record: return record
        if corrects_id:
            prior = self.storage.get(patient, corrects_id)
            if not prior or prior["type"] != "OBSERVATION" or prior.get("corrects_id"):
                raise ValueError("observation correction target is unavailable")
        # Use storage directly so a caregiver's narrowly-scoped write does not
        # acquire patient ownership. This is still patient-scoped and audited
        # through the immutable actor_id field.
        record_id, now = self._id(), self._now()
        record = self.storage.put(patient, record_id, "OBSERVATION", payload | {"created_at": now, "updated_at": now, "reviewed": True, "actor_id": identity.subject_id, "excerpt": f"pain score {pain_score}"}, expires_at=now + self.retention_days * 86400 if self.retention_days is not None else None)
        self.storage.index(patient, record_id, "search-" + record_id, record["excerpt"], now)
        self.storage.idempotency_put(patient, "observation", idempotency_key, record_id, fingerprint)
        self.evaluate_rules(patient)
        return record

    def evaluate_rules(self, patient: str) -> list[dict[str, Any]]:
        """Evaluate active, source-cited rules only; each consecutive run is one episode."""
        observations = self._effective_observations(patient)
        created: list[dict[str, Any]] = []
        qualifying_episode_keys: set[str] = set()
        for rule in self.storage.list(patient, "PLAN_RULE"):
            spec = self._rule_spec(rule)
            if rule.get("status") != "active" or not rule.get("reviewed") or not rule.get("source_id") or not spec: continue
            source = self.storage.get(patient, rule["source_id"])
            if not source or not source.get("reviewed"): continue
            daily: dict[str, dict[str, Any]] = {}
            for row in observations:
                key = self._day(row["observed_at"])
                if key not in daily or (row["observed_at"], row["created_at"], row["id"]) > (daily[key]["observed_at"], daily[key]["created_at"], daily[key]["id"]): daily[key] = row
            run_start: str | None = None; run_days = 0; previous: datetime | None = None
            for day in sorted(daily):
                current = datetime.fromisoformat(day)
                contiguous = previous is not None and (current - previous).days == 1
                value = daily[day]["pain_score"]
                if value >= spec["threshold"]:
                    if not contiguous: run_start, run_days = day, 0
                    run_days += 1
                    if run_days == spec["consecutive_days"]:
                        episode_key = f"{rule['id']}:{run_start}"
                        qualifying_episode_keys.add(episode_key)
                        if not any(alert.get("episode_key") == episode_key and alert.get("status", "active") == "active" for alert in self.storage.list(patient, "ALERT")):
                            now = self._now(); alert_id = self._id()
                            # No delivery integration exists in this synthetic
                            # service: failure is explicit, never silent.
                            alert = self.storage.put(patient, alert_id, "ALERT", {"created_at": now, "updated_at": now, "reviewed": True, "actor_id": "careloop-rule-engine", "rule_id": rule["id"], "source_id": rule["source_id"], "episode_key": episode_key, "episode_start": run_start, "episode_end": day, "status": "active", "delivery_status": "failed", "acknowledgements": []}, expires_at=None)
                            created.append(alert)
                else: run_start, run_days = None, 0
                previous = current
        # Corrections can remove a previously qualifying run.  Keep the
        # historical alert record, but invalidate it so it cannot be shown,
        # acknowledged, or included as a current alert in a handoff.
        for alert in self.storage.list(patient, "ALERT"):
            if alert.get("status", "active") == "active" and alert.get("episode_key") not in qualifying_episode_keys:
                alert |= {"status": "invalidated", "invalidated_at": self._now(), "updated_at": self._now()}
                self.storage.put(patient, alert["id"], "ALERT", alert, expires_at=None)
        return created

    def list_care_tasks(self, identity: Identity) -> list[dict[str, Any]]:
        patient = self.patient_for(identity, "read_tasks" if identity.role == "caregiver" else None)
        tasks = [row for row in self.storage.list(patient) if row["type"] in {"PLAN_TASK", "PLAN_RULE"}]
        # An unapproved proposal is private to the patient, including when a
        # caregiver otherwise has task-reading access.
        if identity.role == "caregiver":
            tasks = [row for row in tasks if row.get("status", "active") == "active"]
        return tasks

    def record_task_completion(self, identity: Identity, task_id: str, completed_at: int | None = None) -> dict[str, Any]:
        patient = self._require_patient(identity)
        task = self.storage.get(patient, task_id)
        if not task or task["type"] != "PLAN_TASK" or task.get("status", "active") != "active":
            raise ValueError("active care task is unavailable")
        when = self._now() if completed_at is None else int(completed_at)
        if when < 0:
            raise ValueError("completion timestamp is invalid")
        return self.write(identity, "TASK_EVENT", {"task_id": task_id, "event": "completed", "completed_at": when},
                          source_id=task.get("source_id"), reviewed=True)
    def search(self, identity: Identity, query: str, *, from_date: int | None=None, to_date: int | None=None) -> list[dict[str, Any]]:
        if from_date is not None and to_date is not None and from_date > to_date: raise ValueError("invalid date range")
        patient = self.patient_for(identity)
        allowed = self._caregiver_record_types(identity)
        # A corrected measurement is historical evidence, not current
        # retrieval evidence. Its correction remains source-linked instead.
        superseded = {row.get("corrects_id") for row in self.storage.list(patient, "OBSERVATION") if row.get("corrects_id")}
        return [r for r in self.storage.search(patient,query)
                if r["type"] in allowed
                and r["id"] not in superseded
                and (from_date is None or r.get("observed_at", r["created_at"]) >= from_date)
                and (to_date is None or r.get("observed_at", r["created_at"]) <= to_date)]

    def list_observations(self, identity: Identity, *, from_date: int | None = None, to_date: int | None = None) -> list[dict[str, Any]]:
        if from_date is not None and to_date is not None and from_date > to_date: raise ValueError("invalid date range")
        patient = self.patient_for(identity, "read_observations" if identity.role == "caregiver" else None)
        rows = [row for row in self._effective_observations(patient)
                if (from_date is None or row["observed_at"] >= from_date) and (to_date is None or row["observed_at"] <= to_date)]
        return sorted(rows, key=lambda row: (row["observed_at"], row["created_at"], row["id"]))

    def create_visit_handoff(self, identity: Identity, from_date: int, to_date: int) -> dict[str, Any]:
        """Create a patient-only factual, date-bounded record for clinician discussion.

        The handoff deliberately contains no interpretation of missing data or
        recommendation; it is a projection of authoritative source records.
        """
        patient = self._require_patient(identity)
        if from_date < 0 or to_date < from_date: raise ValueError("invalid handoff date range")
        plans = [row for row in self.storage.list(patient) if row["type"] in {"PLAN_TASK", "PLAN_RULE"} and row.get("status") == "active"]
        plan_items = []
        for row in plans:
            source = self.storage.get(patient, row["source_id"]) if row.get("source_id") else None
            citation = None if not source else {"source_id": source["id"], "title": source.get("title", "Approved source"), "page_excerpts": source.get("page_excerpts", [])}
            plan_items.append({"plan_id": row["id"], "type": row["type"], "status": row.get("status", "unknown"), "text": row.get("text", ""), "source_id": row.get("source_id"), "source_citation": citation})
        events = [row for row in self.storage.list(patient, "TASK_EVENT") if from_date <= row.get("completed_at", row["created_at"]) <= to_date]
        observations = self.list_observations(identity, from_date=from_date, to_date=to_date)
        all_observations = self.storage.list(patient, "OBSERVATION")
        corrections = [{"correction_id": row["id"], "corrects_id": row["corrects_id"]} for row in all_observations if row.get("corrects_id") and from_date <= row.get("observed_at", 0) <= to_date]
        alerts = [row for row in self.storage.list(patient, "ALERT") if row.get("status", "active") == "active" and from_date <= row.get("created_at", 0) <= to_date]
        data = {"label": "Patient-generated factual summary for clinician discussion", "from_date": from_date, "to_date": to_date,
                "plan_items": plan_items, "task_events": events, "observations": observations, "alerts": alerts,
                "corrections": corrections, "uncertainties": ["No observation is recorded for dates absent from this handoff."],
                "totals": {"plan_items": len(plan_items), "task_events": len(events), "observations": len(observations), "alerts": len(alerts), "corrections": len(corrections)}}
        return self.write(identity, "HANDOFF", data, reviewed=True)

    def mark_alert_delivery(self, identity: Identity, alert_id: str, status: str) -> dict[str, Any]:
        patient = self._require_patient(identity)
        if status not in {"delivered", "failed"}: raise ValueError("invalid delivery status")
        alert = self.storage.get(patient, alert_id)
        if not alert or alert["type"] != "ALERT": raise ValueError("alert is unavailable")
        alert |= {"delivery_status": status, "updated_at": self._now()}
        return self.storage.put(patient, alert_id, "ALERT", alert, expires_at=None)

    def list_records(self, identity: Identity, record_type: str | None = None) -> list[dict[str, Any]]:
        """Return only record classes explicitly covered by the caller's grant."""
        patient = self.patient_for(identity)
        allowed = self._caregiver_record_types(identity)
        if record_type is not None and record_type not in allowed:
            raise AccessDenied("Caregiver scope does not allow this record type")
        records = self.storage.list(patient, record_type)
        return [record for record in records if record["type"] in allowed]

    def source_excerpt(self, identity: Identity, source_id: str) -> dict[str, Any]:
        """Return an explicitly requested, reviewed source excerpt.

        Caregivers cannot enumerate documents.  They may see a source only
        when it is linked to a plan task/rule that their ``read_tasks`` grant
        already authorizes.  The response is a whitelisted excerpt view, not
        the stored document record.
        """
        patient = self.patient_for(identity, "read_tasks")
        source = self.storage.get(patient, source_id)
        if not source or source["type"] != "DOCUMENT" or not source.get("reviewed"):
            raise AccessDenied("Source is unavailable")
        if identity.role == "caregiver":
            linked = any(
                record.get("source_id") == source_id and record.get("status", "active") == "active"
                for record in self.storage.list(patient)
                if record["type"] in {"PLAN_TASK", "PLAN_RULE"}
            )
            if not linked:
                raise AccessDenied("Source is unavailable")
        return {
            "source_id": source["id"],
            "title": source.get("title", "Approved source"),
            "page_excerpts": source.get("page_excerpts", []),
        }
    def export(self, identity: Identity) -> dict[str, Any]:
        patient=self._require_patient(identity)
        records=[r for r in self.storage.list(patient) if r["type"] != "AUDIT"]
        return {"patient_id":patient,"exported_at":self._now(),"records":records,"count":len(records)}
    def delete(self, identity: Identity, record_id: str) -> bool:
        return self.storage.soft_delete(self._require_patient(identity),record_id,self._now())
    def delete_all(self, identity: Identity) -> int:
        patient=self._require_patient(identity); return sum(self.storage.soft_delete(patient,r["id"],self._now()) for r in self.storage.list(patient))
    def purge(self, identity: Identity) -> int:
        """Physically purge only the authenticated patient's expired/deleted data."""
        return self.storage.purge(self._now(), patient_id=self._require_patient(identity))
    def audit(self, identity: Identity, action: str, outcome: str) -> dict[str, Any]:
        """Store metadata only; clinical content must never enter CareLoop audit records."""
        if action not in AUDIT_ACTIONS or outcome not in AUDIT_OUTCOMES:
            raise ValueError("invalid CareLoop audit metadata")
        patient = self._require_patient(identity)
        record_id = self._id()
        return self.storage.put(patient, record_id, "AUDIT", {
            "created_at": self._now(), "actor_id": identity.subject_id,
            "action": action, "outcome": outcome,
        })
    def invite(self, identity: Identity, scopes: list[str], expires_at: int | None = None) -> dict[str, Any]:
        """Create a patient-owned, pending invitation with no caregiver binding yet."""
        if not scopes or not set(scopes) <= CAREGIVER_SCOPES:
            raise ValueError("invalid caregiver scope")
        if expires_at is not None and expires_at <= self._now():
            raise ValueError("invitation expiry must be in the future")
        # The storage record ID becomes the opaque invitation identifier.
        saved = self.write(identity, "CONSENT", {
            "scopes": sorted(set(scopes)), "expires_at": expires_at,
            "status": "pending",
        })
        saved["invitation_id"] = saved["id"]
        saved = self.storage.put(identity.patient, saved["id"], "CONSENT", saved, expires_at=expires_at)
        self.audit(identity, "access_invited", "success")
        return saved

    def accept_invitation(self, identity: Identity, invitation_id: str) -> dict[str, Any]:
        """Bind an unexpired invitation to the *authenticated* caregiver identity."""
        if identity.role != "caregiver":
            raise AccessDenied("Only an authenticated caregiver may accept an invitation")
        patient = identity.patient
        invitation = self.storage.get(patient, invitation_id)
        if not invitation or invitation["type"] != "CONSENT" or invitation.get("invitation_id") != invitation_id:
            raise AccessDenied("Invitation is unavailable")
        if invitation.get("accepted_at") or invitation.get("revoked_at"):
            raise AccessDenied("Invitation is no longer available")
        if invitation.get("expires_at") and invitation["expires_at"] <= self._now():
            raise AccessDenied("Invitation has expired")
        invitation |= {"caregiver_id": identity.subject_id, "accepted_at": self._now(), "status": "active", "updated_at": self._now()}
        saved = self.storage.put(patient, invitation["id"], "CONSENT", invitation, expires_at=invitation.get("expires_at"))
        # Consent audit events deliberately contain no invitation, person, or clinical details.
        self.audit(self._patient_identity(patient), "access_granted", "success")
        return saved

    def _patient_identity(self, patient: str) -> Identity:
        return Identity(patient, "patient", patient)

    def grant(self, identity: Identity, caregiver_id: str, scopes: list[str], expires_at: int | None=None) -> dict[str, Any]:
        """Compatibility helper for seeded synthetic demos; portal code uses invite/accept."""
        invitation = self.invite(identity, scopes, expires_at)
        accepted = dict(invitation) | {"caregiver_id": caregiver_id, "accepted_at": self._now(), "status": "active", "updated_at": self._now()}
        return self.storage.put(identity.patient, invitation["id"], "CONSENT", accepted, expires_at=expires_at)

    def list_grants(self, identity: Identity) -> list[dict[str, Any]]:
        return self.storage.list(self._require_patient(identity), "CONSENT")

    def revoke(self, identity: Identity, caregiver_id: str | None = None, *, invitation_id: str | None = None) -> int:
        patient=self._require_patient(identity); count=0
        for grant in self.storage.list(patient,"CONSENT"):
            if (invitation_id and grant["id"] == invitation_id) or (caregiver_id and grant.get("caregiver_id") == caregiver_id):
                grant["revoked_at"]=self._now(); grant["status"]="revoked"; grant["updated_at"]=self._now()
                self.storage.put(patient,grant["id"],"CONSENT",grant,expires_at=grant.get("expires_at")); count+=1
        if count:
            self.audit(identity, "access_revoked", "success")
        return count

    def notifications(self, identity: Identity) -> list[dict[str, str]]:
        """Return generic notification state only; alert content stays private."""
        patient = self.patient_for(identity, "receive_alerts")
        if identity.role != "caregiver":
            raise AccessDenied("Notifications are routed to authorized caregivers")
        def state(alert: dict[str, Any]) -> str:
            acknowledged = any(row.get("caregiver_id") == identity.subject_id for row in alert.get("acknowledgements", []))
            return "acknowledged" if acknowledged else "action_required"
        return [{"case_id": alert["id"], "status": state(alert)}
                for alert in self.storage.list(patient, "ALERT") if alert.get("status", "active") == "active"]

    def acknowledge_alert(self, identity: Identity, alert_id: str) -> dict[str, Any]:
        patient = self.patient_for(identity, "acknowledge_alerts")
        alert = self.storage.get(patient, alert_id)
        if not alert or alert["type"] != "ALERT" or alert.get("status", "active") != "active":
            raise AccessDenied("Alert is unavailable")
        acknowledgements = list(alert.get("acknowledgements", []))
        if not any(row.get("caregiver_id") == identity.subject_id for row in acknowledgements):
            acknowledgements.append({"caregiver_id": identity.subject_id, "acknowledged_at": self._now()})
        alert |= {"acknowledgements": acknowledgements, "updated_at": self._now()}
        self.storage.put(patient, alert_id, "ALERT", alert, expires_at=None)
        # The stored audit action has a closed vocabulary and no alert content.
        self.audit(self._patient_identity(patient), "alert_acknowledged", "success")
        # Do not return the ALERT record: acknowledgement permission is not
        # permission to read the alert's clinical details.
        return {"case_id": alert_id, "status": "acknowledged"}
