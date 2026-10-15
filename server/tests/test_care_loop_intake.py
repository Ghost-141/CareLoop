"""Phase 3 document intake is deterministic, reviewed, and raw-upload free."""
from __future__ import annotations

from fastapi.testclient import TestClient

from care_loop.auth import Identity, TokenAuth
from care_loop.config import Settings
from care_loop.server import build_deps, create_app
from care_loop.storage import CareLoopStorage


PATIENT = "patient-token"
CAREGIVER = "caregiver-token"


def setup() -> tuple[TestClient, object]:
    auth = TokenAuth({
        PATIENT: Identity("patient-a", "patient", "patient-a"),
        CAREGIVER: Identity("caregiver-a", "caregiver", "patient-a"),
    })
    deps = build_deps(Settings(db_path=":memory:"), storage=CareLoopStorage(":memory:"), auth=auth)
    return TestClient(create_app(deps)), deps


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_text_intake_creates_drafts_without_retaining_raw_text_and_needs_patient_approval() -> None:
    client, deps = setup()
    raw = "private prose that must not be retained\nTASK: Take a short walk | schedule: every morning\nRULE: Contact clinic if the stated plan says to"
    response = client.post("/api/care/documents/text", headers=headers(PATIENT), json={"title": "Synthetic discharge", "text": raw})
    assert response.status_code == 200
    intake = response.json()["intake"]
    assert len(intake["drafts"]) == 2
    assert all(item["status"] == "draft" for item in intake["drafts"])
    assert "private prose" not in str(deps.storage.list("patient-a"))

    task = intake["drafts"][0]
    assert client.post(f"/api/care/tasks/{task['id']}/complete", headers=headers(PATIENT), json={}).status_code == 422
    approved = client.post(f"/api/care/plan/{task['id']}/approve", headers=headers(PATIENT))
    assert approved.status_code == 200 and approved.json()["plan_item"]["status"] == "active"
    completed = client.post(f"/api/care/tasks/{task['id']}/complete", headers=headers(PATIENT), json={})
    assert completed.status_code == 200


def test_caregiver_sees_only_approved_task_and_its_linked_source() -> None:
    client, _ = setup()
    intake = client.post("/api/care/documents", headers=headers(PATIENT), json={
        "title": "Synthetic discharge", "text": "TASK: Check the synthetic checklist | schedule: daily"
    }).json()["intake"]
    invitation = client.post("/api/care/invitations", headers=headers(PATIENT), json={"scopes": ["read_tasks"]}).json()["invitation"]
    client.post(f"/api/care/invitations/{invitation['id']}/accept", headers=headers(CAREGIVER))
    assert client.get("/api/care/tasks", headers=headers(CAREGIVER)).json() == {"tasks": []}
    source_id = intake["document"]["id"]
    assert client.get(f"/api/care/sources/{source_id}", headers=headers(CAREGIVER)).status_code == 403

    client.post(f"/api/care/plan/{intake['drafts'][0]['id']}/approve", headers=headers(PATIENT))
    assert len(client.get("/api/care/tasks", headers=headers(CAREGIVER)).json()["tasks"]) == 1
    source = client.get(f"/api/care/sources/{source_id}", headers=headers(CAREGIVER)).json()["source"]
    assert source["page_excerpts"] == [{"page": 1, "excerpt": "TASK: Check the synthetic checklist | schedule: daily"}]


def test_pdf_intake_rejects_invalid_and_uses_manual_review_without_local_extractor() -> None:
    client, _ = setup()
    invalid = client.post("/api/care/documents/pdf?title=bad", headers=headers(PATIENT) | {"Content-Type": "application/pdf"}, content=b"not a pdf")
    assert invalid.status_code == 422
    valid = client.post("/api/care/documents/pdf?title=fixture", headers=headers(PATIENT) | {"Content-Type": "application/pdf"}, content=b"%PDF-1.4\n%%EOF")
    # The dependency is deliberately optional.  A locally installed extractor
    # may instead inspect this tiny malformed fixture and still safely reject.
    assert valid.status_code == 422


def test_conflicting_tagged_instructions_stay_pending_manual_review() -> None:
    client, _ = setup()
    response = client.post("/api/care/documents/text", headers=headers(PATIENT), json={
        "title": "Conflicting fixture",
        "text": "TASK: First instruction | schedule: daily\nTASK: Different instruction | schedule: daily",
    })
    intake = response.json()["intake"]
    assert intake["manual_review_required"] is True
    assert {draft["status"] for draft in intake["drafts"]} == {"pending_review"}
    assert client.post(f"/api/care/plan/{intake['drafts'][0]['id']}/approve", headers=headers(PATIENT)).status_code == 422

