"""Direct HTTP authorization checks for the Phase 2 private CareLoop portal."""
from __future__ import annotations

from fastapi.testclient import TestClient

from care_loop.auth import Identity, TokenAuth
from care_loop.config import Settings
from care_loop.server import build_deps, create_app
from care_loop.storage import CareLoopStorage


PATIENT = "patient-token"
CAREGIVER = "caregiver-token"
OTHER = "other-token"


def portal(now: list[int]):
    auth = TokenAuth({
        PATIENT: Identity("patient-a", "patient", "patient-a"),
        CAREGIVER: Identity("caregiver-a", "caregiver", "patient-a"),
        OTHER: Identity("caregiver-b", "caregiver", "patient-a"),
    })
    storage = CareLoopStorage(":memory:", clock=lambda: now[0])
    deps = build_deps(Settings(db_path=":memory:"), storage=storage, auth=auth, clock=lambda: now[0])
    return TestClient(create_app(deps)), deps


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_invitation_binds_authenticated_caregiver_and_scope_is_enforced() -> None:
    client, deps = portal([100])
    created = client.post("/api/care/invitations", headers=headers(PATIENT), json={"scopes": ["read_tasks"], "expires_at": 200})
    assert created.status_code == 200
    invitation_id = created.json()["invitation"]["id"]

    assert client.post(f"/api/care/invitations/{invitation_id}/accept", headers=headers(CAREGIVER)).status_code == 200
    assert client.get("/api/care/grants", headers=headers(PATIENT)).json()["grants"][0]["caregiver_id"] == "caregiver-a"
    assert client.get("/api/care/records?record_type=OBSERVATION", headers=headers(CAREGIVER)).status_code == 403
    assert client.post(f"/api/care/invitations/{invitation_id}/accept", headers=headers(OTHER)).status_code == 403


def test_expired_and_revoked_grants_are_denied_on_direct_requests() -> None:
    now = [100]
    client, deps = portal(now)
    alert = deps.service.write(Identity("patient-a", "patient", "patient-a"), "ALERT", {"text": "synthetic detail"})
    response = client.post("/api/care/invitations", headers=headers(PATIENT), json={"scopes": ["receive_alerts"], "expires_at": 101})
    invitation_id = response.json()["invitation"]["id"]
    assert client.post(f"/api/care/invitations/{invitation_id}/accept", headers=headers(CAREGIVER)).status_code == 200
    assert client.get("/api/care/notifications", headers=headers(CAREGIVER)).status_code == 200
    now[0] = 101
    assert client.get("/api/care/notifications", headers=headers(CAREGIVER)).status_code == 403

    now[0] = 102
    new = client.post("/api/care/invitations", headers=headers(PATIENT), json={"scopes": ["receive_alerts"]}).json()["invitation"]
    assert client.post(f"/api/care/invitations/{new['id']}/accept", headers=headers(CAREGIVER)).status_code == 200
    assert client.post(f"/api/care/grants/{new['id']}/revoke", headers=headers(PATIENT)).json() == {"revoked": True}
    assert client.get("/api/care/notifications", headers=headers(CAREGIVER)).status_code == 403


def test_notifications_are_generic_and_acknowledgement_needs_its_own_scope() -> None:
    client, deps = portal([100])
    patient = Identity("patient-a", "patient", "patient-a")
    alert = deps.service.write(patient, "ALERT", {"text": "pain score 9", "medication": "synthetic"})
    invite = client.post("/api/care/invitations", headers=headers(PATIENT), json={"scopes": ["receive_alerts"]}).json()["invitation"]
    client.post(f"/api/care/invitations/{invite['id']}/accept", headers=headers(CAREGIVER))
    notices = client.get("/api/care/notifications", headers=headers(CAREGIVER)).json()["notifications"]
    assert notices == [{"case_id": alert["id"], "status": "action_required"}]
    assert "pain" not in str(notices).lower() and "medication" not in str(notices).lower()
    assert client.get("/api/care/records?record_type=ALERT", headers=headers(CAREGIVER)).status_code == 403
    assert client.post(f"/api/care/alerts/{alert['id']}/acknowledge", headers=headers(CAREGIVER)).status_code == 403

    ack = client.post("/api/care/invitations", headers=headers(PATIENT), json={"scopes": ["acknowledge_alerts"]}).json()["invitation"]
    client.post(f"/api/care/invitations/{ack['id']}/accept", headers=headers(CAREGIVER))
    response = client.post(f"/api/care/alerts/{alert['id']}/acknowledge", headers=headers(CAREGIVER))
    assert response.status_code == 200
    assert response.json() == {"acknowledgement": {"case_id": alert["id"], "status": "acknowledged"}}
    assert "pain" not in response.text.lower() and "medication" not in response.text.lower()
    audits = deps.storage.list("patient-a", "AUDIT")
    assert all("pain" not in str(record).lower() and "medication" not in str(record).lower() for record in audits)


def test_read_tasks_cannot_list_documents_but_can_fetch_linked_reviewed_source_excerpt() -> None:
    client, deps = portal([100])
    patient = Identity("patient-a", "patient", "patient-a")
    document = deps.service.create_document(
        patient, "Synthetic discharge", [{"page": 2, "excerpt": "Reviewed instruction"}], reviewed=True
    )
    deps.service.write(patient, "PLAN_TASK", {"text": "Follow instruction"}, source_id=document["id"])
    unlinked = deps.service.create_document(
        patient, "Unlinked synthetic note", [{"page": 1, "excerpt": "Do not disclose"}], reviewed=True
    )
    invite = client.post("/api/care/invitations", headers=headers(PATIENT), json={"scopes": ["read_tasks"]}).json()["invitation"]
    assert client.post(f"/api/care/invitations/{invite['id']}/accept", headers=headers(CAREGIVER)).status_code == 200

    assert client.get("/api/care/records?record_type=DOCUMENT", headers=headers(CAREGIVER)).status_code == 403
    records = client.get("/api/care/records", headers=headers(CAREGIVER)).json()["records"]
    assert [record["type"] for record in records] == ["PLAN_TASK"]
    source = client.get(f"/api/care/sources/{document['id']}", headers=headers(CAREGIVER))
    assert source.json() == {"source": {"source_id": document["id"], "title": "Synthetic discharge", "page_excerpts": [{"page": 2, "excerpt": "Reviewed instruction"}]}}
    assert client.get(f"/api/care/sources/{unlinked['id']}", headers=headers(CAREGIVER)).status_code == 403
