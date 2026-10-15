"""Offline invariants for the deliberately separate CareLoop demo store."""
from __future__ import annotations

import pytest

from care_loop.auth import Identity
from care_loop.core import AccessDenied, CareLoopService
from care_loop.storage import CareLoopStorage


def patient(name: str) -> Identity:
    return Identity(name, "patient", name)


def test_patients_cannot_cross_read_or_delete() -> None:
    store = CareLoopStorage(":memory:")
    service = CareLoopService(store)
    first = service.write(patient("one"), "PLAN_TASK", {"text": "Use the synthetic checklist"})
    assert service.search(patient("one"), "checklist") == [first]
    assert service.search(patient("two"), "checklist") == []
    assert service.delete(patient("two"), first["id"]) is False
    assert service.search(patient("one"), "checklist") == [first]


def test_caregiver_revocation_takes_effect_on_next_request() -> None:
    store = CareLoopStorage(":memory:")
    service = CareLoopService(store)
    owner = patient("one")
    service.write(owner, "PLAN_TASK", {"text": "Reviewed source task"})
    service.grant(owner, "caregiver", ["read_tasks"])
    caregiver = Identity("caregiver", "caregiver", "one")
    assert service.search(caregiver, "source")
    assert service.revoke(owner, "caregiver") == 1
    with pytest.raises(AccessDenied):
        service.search(caregiver, "source")


def test_restart_preserves_source_and_retrieval_index(tmp_path) -> None:
    path = tmp_path / "careloop.db"
    first_store = CareLoopStorage(path)
    first_service = CareLoopService(first_store)
    first_service.write(patient("one"), "DOCUMENT", {"title": "Synthetic discharge", "excerpt": "Reviewed follow-up plan"})
    first_store.close()
    second_store = CareLoopStorage(path)
    found = CareLoopService(second_store).search(patient("one"), "follow-up")
    assert len(found) == 1 and found[0]["title"] == "Synthetic discharge"
    second_store.close()


def test_delete_and_expiry_remove_derived_entries_then_purge(tmp_path) -> None:
    now = [100]
    store = CareLoopStorage(tmp_path / "careloop.db", clock=lambda: now[0])
    service = CareLoopService(store, clock=lambda: now[0])
    owner = patient("one")
    deleted = service.write(owner, "DOCUMENT", {"excerpt": "corrected keyword"})
    expired = service.write(owner, "DOCUMENT", {"excerpt": "expired keyword"}, expires_at=101)
    assert service.search(owner, "corrected")
    assert service.delete(owner, deleted["id"])
    assert not service.search(owner, "corrected")
    now[0] = 102
    assert not service.search(owner, "expired")
    assert service.purge(owner) == 2
    assert store.list("one") == []


def test_export_is_patient_scoped_and_excludes_no_other_patient() -> None:
    store = CareLoopStorage(":memory:")
    service = CareLoopService(store)
    service.write(patient("one"), "OBSERVATION", {"unit": "score", "value": 3})
    service.write(patient("two"), "OBSERVATION", {"unit": "score", "value": 7})
    export = service.export(patient("one"))
    assert export["patient_id"] == "one" and export["count"] == 1
    assert export["records"][0]["value"] == 3


def test_observation_only_caregiver_cannot_manage_patient_data() -> None:
    """A read grant is never an ownership, export, deletion, or retention grant."""
    store = CareLoopStorage(":memory:")
    service = CareLoopService(store)
    owner = patient("one")
    record = service.write(owner, "OBSERVATION", {"unit": "score", "value": 3})
    service.grant(owner, "caregiver", ["read_observations"])
    caregiver = Identity("caregiver", "caregiver", "one")

    assert service.list_records(caregiver, "OBSERVATION") == [record]
    for operation in (
        lambda: service.write(caregiver, "OBSERVATION", {"unit": "score", "value": 4}),
        lambda: service.delete(caregiver, record["id"]),
        lambda: service.delete_all(caregiver),
        lambda: service.export(caregiver),
        lambda: service.purge(caregiver),
    ):
        with pytest.raises(AccessDenied):
            operation()

    assert service.list_records(owner, "OBSERVATION") == [record]


def test_caregiver_scopes_filter_record_classes_and_search_results() -> None:
    store = CareLoopStorage(":memory:")
    service = CareLoopService(store)
    owner = patient("one")
    service.write(owner, "PLAN_TASK", {"text": "review checklist"})
    observation = service.write(owner, "OBSERVATION", {"text": "pain score", "value": 3})
    service.grant(owner, "caregiver", ["read_observations"])
    caregiver = Identity("caregiver", "caregiver", "one")

    assert service.search(caregiver, "checklist") == []
    assert service.search(caregiver, "pain") == [observation]
    with pytest.raises(AccessDenied):
        service.list_records(caregiver, "PLAN_TASK")


def test_audit_rejects_phi_like_caller_supplied_metadata() -> None:
    service = CareLoopService(CareLoopStorage(":memory:"))
    owner = patient("one")

    with pytest.raises(ValueError, match="audit metadata"):
        service.audit(owner, "patient pain score is 9", "improved after medication")

    audit = service.audit(owner, "data_exported", "success")
    assert audit["action"] == "data_exported"
    assert audit["outcome"] == "success"
