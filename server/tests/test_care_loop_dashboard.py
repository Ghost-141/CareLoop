"""Browser-facing dashboard contract tests for the private synthetic demo."""
from __future__ import annotations

from fastapi.testclient import TestClient

from care_loop.auth import Identity, TokenAuth
from care_loop.config import Settings
from care_loop.server import build_deps, create_app
from care_loop.storage import CareLoopStorage


PATIENT_TOKEN = "patient-demo-token"
CAREGIVER_TOKEN = "caregiver-demo-token"


def client() -> TestClient:
    auth = TokenAuth({
        PATIENT_TOKEN: Identity("patient-demo", "patient", "patient-demo"),
        CAREGIVER_TOKEN: Identity("caregiver-demo", "caregiver", "patient-demo"),
    })
    storage = CareLoopStorage(":memory:", clock=lambda: 1_700_000_000)
    deps = build_deps(Settings(db_path=":memory:"), storage=storage, auth=auth, clock=lambda: 1_700_000_000)
    return TestClient(create_app(deps))


def test_dashboard_is_public_shell_with_private_api_sign_in() -> None:
    app = client()
    response = app.get("/care")
    assert response.status_code == 200
    page = response.text
    assert "Open a private demo session" in page
    assert "sessionStorage" in page
    assert "careloopToken" in page
    assert "Demo only — not medical advice or emergency monitoring." in page
    assert "CareLoop" in page
    # The HTML never embeds either token or an authorization value.
    assert PATIENT_TOKEN not in page
    assert CAREGIVER_TOKEN not in page


def test_dashboard_exposes_all_planned_private_demo_views_and_safe_actions() -> None:
    page = client().get("/care").text
    for label in ("Today", "Plan review", "Track", "Sharing", "Handoff"):
        assert label in page
    for route in ("/documents/text", "/plan/", "/tasks/", "/observations", "/invitations", "/handoffs", "/alerts/"):
        assert route in page
    assert "crypto.randomUUID" in page
    assert "No private care details are shown here." in page
    assert "aria-live" in page
    assert ":focus-visible" in page
    assert "@media" in page


def test_dashboard_api_contract_keeps_caregiver_alerts_generic() -> None:
    app = client()
    patient_headers = {"Authorization": f"Bearer {PATIENT_TOKEN}"}
    caregiver_headers = {"Authorization": f"Bearer {CAREGIVER_TOKEN}"}
    invitation = app.post("/api/care/invitations", headers=patient_headers, json={"scopes": ["receive_alerts", "acknowledge_alerts"]}).json()["invitation"]
    assert app.post(f"/api/care/invitations/{invitation['id']}/accept", headers=caregiver_headers).status_code == 200
    # The dashboard calls the deliberately generic notification route; sensitive
    # record-list access remains denied for the caregiver.
    assert app.get("/api/care/notifications", headers=caregiver_headers).status_code == 200
    assert app.get("/api/care/records?record_type=ALERT", headers=caregiver_headers).status_code == 403
