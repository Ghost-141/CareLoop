"""Document intake: PDF text → OCR fallback → model proposal → deterministic checks → review."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from care_loop.auth import Identity, TokenAuth
from care_loop.config import Settings
from care_loop.core import AccessDenied, CareLoopService
from care_loop.extraction import ExtractionError, extract_document, sniff
from care_loop.extraction.lines import SourceLine
from care_loop.extraction.pdf_text import page_needs_ocr
from care_loop.server import build_deps, create_app
from care_loop.storage import CareLoopStorage
from care_loop.structuring import ModelUnavailable, OllamaIntakeModel, structure_document
from care_loop.structuring.schema import Extraction, ExtractedItem, Medication, RuleCandidate, Schedule
from care_loop.structuring.validate import detect_frequency, suggested_times, validate

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "evals" / "intake"))
from documents import EXPECTED_PRESCRIPTION, INJECTION, PRESCRIPTION, make_pdf  # noqa: E402

NOW = 1_791_936_000
PATIENT = Identity("demo-patient", "patient", "demo-patient")
CAREGIVER = Identity("demo-caregiver", "caregiver", "demo-patient")


def lines_of(texts: list[str], method: str = "text", confidence: int = 100) -> list[SourceLine]:
    return [SourceLine(1, i, t, method, confidence) for i, t in enumerate(texts, start=1)]


class FakeModel:
    name = "fake-model"

    def __init__(self, extraction: Extraction | None = None, fail: bool = False) -> None:
        self.extraction, self.fail, self.calls = extraction, fail, 0

    def structure(self, lines, *, today, doc_type):
        self.calls += 1
        if self.fail:
            raise ModelUnavailable("The local model is unreachable.")
        return self.extraction


class FakeOcr:
    def __init__(self, confidence: int = 97) -> None:
        self.confidence, self.pages = confidence, []

    def read_pdf_page(self, data, *, page):
        self.pages.append(page)
        return [SourceLine(page, i, t, "ocr", self.confidence) for i, t in enumerate(
            [l for l in PRESCRIPTION if l], start=1)]

    def read_image(self, data, *, page=1):
        return self.read_pdf_page(data, page=page)


class Engines:
    def __init__(self, model=None, ocr=None) -> None:
        self._model, self._ocr = model, ocr

    def model(self):
        return self._model

    def ocr(self):
        return self._ocr


def good_extraction() -> Extraction:
    return Extraction(items=[
        ExtractedItem(kind="medication_task", label="Amoxicillin morning", source_lines=["p1:L5"],
                      instruction_verbatim="Take 1 capsule by mouth three times daily for 7 days.",
                      medication=Medication(name="Amoxicillin", strength="500 mg", dose="1 capsule", route="by mouth"),
                      schedule=Schedule(frequency="three_times_daily", duration_days=7)),
        ExtractedItem(kind="care_task", label="Short walk", source_lines=["p1:L9"],
                      instruction_verbatim="Take a short walk every morning.", schedule=Schedule(frequency="once_daily")),
        ExtractedItem(kind="warning_sign", label="Pain follow-up", source_lines=["p1:L11"],
                      instruction_verbatim="Contact the clinic if your pain score is 7 or higher for 2 consecutive days."),
    ])


def service(model=None, ocr=None, now=None) -> CareLoopService:
    clock = now or [NOW]
    svc = CareLoopService(CareLoopStorage(":memory:", clock=lambda: clock[0]), clock=lambda: clock[0])
    svc.intake = Engines(model, ocr)
    return svc


# ---- extraction --------------------------------------------------------------------------------
def test_typed_pdf_becomes_numbered_lines_without_ocr() -> None:
    doc = extract_document(make_pdf([PRESCRIPTION]), ocr=None)
    assert doc.page_methods == {1: "text"}
    assert [l.id for l in doc.lines][:2] == ["p1:L1", "p1:L2"]
    assert any("three times daily for 7 days" in l.text for l in doc.lines)


def test_scanned_page_goes_to_ocr_and_photo_needs_ocr() -> None:
    blank = make_pdf([[" "]])
    ocr = FakeOcr()
    doc = extract_document(blank, ocr=ocr)
    assert ocr.pages == [1] and doc.page_methods == {1: "ocr"} and doc.used_ocr
    with pytest.raises(ExtractionError, match="No readable text"):
        extract_document(blank, ocr=None)
    with pytest.raises(ExtractionError, match="need OCR"):
        extract_document(b"\x89PNG\r\n\x1a\n" + b"0" * 100, ocr=None)


@pytest.mark.parametrize(("text", "needs"), [
    ("", True), ("a b c", True), ("�" * 40, True), ("T a k e 1 c a p s u l e d a i l y n o w o k", True),
    ("Take 1 capsule by mouth three times daily for 7 days.", False)])
def test_page_quality_check(text, needs) -> None:
    assert page_needs_ocr(text) is needs


def test_unsupported_files_are_refused() -> None:
    with pytest.raises(ExtractionError):
        sniff(b"GIF89a")


# ---- schedule table ----------------------------------------------------------------------------------
@pytest.mark.parametrize(("text", "frequency", "times"), [
    ("Take 1 capsule three times daily for 7 days", "three_times_daily", ["08:00", "14:00", "20:00"]),
    ("once daily before breakfast", "once_daily", ["07:30"]),
    ("every 8 hours as needed for pain", "as_needed", []),
    ("change the dressing every evening", "once_daily", ["19:00"]),
    ("1 tab BID", "twice_daily", ["08:00", "20:00"]),
    ("2 puffs q6h", "four_times_daily", ["08:00", "12:00", "16:00", "20:00"]),
    ("take at 8 pm daily", "once_daily", ["20:00"]),
])
def test_frequency_table(text, frequency, times) -> None:
    assert detect_frequency(text) == frequency
    assert suggested_times(frequency, text) == times


# ---- deterministic checks on the model's proposal --------------------------------------------------------
def test_good_proposal_passes_and_rule_safety_net_applies() -> None:
    doc = extract_document(make_pdf([PRESCRIPTION]))
    out = validate(good_extraction(), doc.lines, engine="fake")
    med, walk, rule = out.items
    assert med.status == "draft" and med.times == ["08:00", "14:00", "20:00"]
    assert med.label == "Medicine routine 1"  # never a drug name on a speaker
    assert walk.status == "draft" and walk.times == ["08:00"]
    assert rule.kind == "rule_candidate" and rule.record_type == "PLAN_RULE"
    assert rule.rule_spec == {"kind": "pain_score_at_or_above", "threshold": 7, "consecutive_days": 2}
    assert rule.status == "needs_review"
    assert "p1:L1" in [l["id"] for l in out.unused_lines]


def test_invented_numbers_wrong_citations_and_mismatches_force_review() -> None:
    lines = lines_of(["Take 1 capsule by mouth twice daily.", "Rest well."])
    bad = Extraction(items=[
        ExtractedItem(kind="medication_task", label="x", source_lines=["p1:L1"], instruction_verbatim="Take 1 capsule by mouth twice daily.",
                      medication=Medication(name="Unlisted", dose="2 capsules"), schedule=Schedule(frequency="once_daily")),
        ExtractedItem(kind="care_task", label="y", source_lines=["p1:L9"], instruction_verbatim="Walk 5 km."),
    ])
    first, second = validate(bad, lines, engine="fake").items
    assert first.status == "needs_review"
    assert any("number not in the source: 2" in r for r in first.reasons)
    assert any("medicine name not found" in r for r in first.reasons)
    assert any("frequency looks like twice daily" in r for r in first.reasons)
    assert second.status == "needs_review"
    assert any("aren't in the document" in r for r in second.reasons)
    assert any("doesn't match the cited text" in r for r in second.reasons)


def test_rule_numbers_must_come_from_the_source() -> None:
    lines = lines_of(["Call us if your pain is bad for a while."])
    fake = Extraction(items=[ExtractedItem(kind="rule_candidate", label="r", source_lines=["p1:L1"],
                                           instruction_verbatim="Call us if your pain is bad for a while.",
                                           rule=RuleCandidate(threshold=7, consecutive_days=2))])
    item = validate(fake, lines, engine="fake").items[0]
    assert item.kind == "warning_sign" and item.rule_spec is None and item.record_type == "PLAN_NOTE"


def test_low_confidence_ocr_and_conflicts_force_review() -> None:
    lines = lines_of(["Amoxicillin: take 1 capsule once daily.", "Amoxicillin: take 1 capsule twice daily."], "ocr", 70)
    proposal = Extraction(items=[
        ExtractedItem(kind="medication_task", label="a", source_lines=["p1:L1"], instruction_verbatim="take 1 capsule once daily.",
                      medication=Medication(name="Amoxicillin")),
        ExtractedItem(kind="medication_task", label="b", source_lines=["p1:L2"], instruction_verbatim="take 1 capsule twice daily.",
                      medication=Medication(name="Amoxicillin")),
    ])
    for item in validate(proposal, lines, engine="fake").items:
        assert item.status == "needs_review"
        assert any("low confidence" in r for r in item.reasons)
        assert any("different instruction for the same medicine" in r for r in item.reasons)


def test_model_failure_falls_back_to_patterns_and_flags_everything() -> None:
    doc = extract_document(make_pdf([PRESCRIPTION]))
    out = structure_document(doc, FakeModel(fail=True), now=NOW)
    assert out.engine == "patterns" and out.items and all(i.status == "needs_review" for i in out.items)
    kinds = [i.kind for i in out.items]
    assert kinds.count("medication_task") == 3 and "rule_candidate" in kinds and "appointment" in kinds
    assert any("pattern matching" in note for note in out.notes)


def test_ollama_model_sends_schema_and_retries_then_gives_up() -> None:
    sent = []
    replies = iter([b'{"message": {"content": "not json"}}',
                    json.dumps({"message": {"content": good_extraction().model_dump_json()}}).encode()])

    def post(url, body):
        sent.append(json.loads(body))
        return next(replies)

    model = OllamaIntakeModel("http://ollama", "local", post=post)
    out = model.structure(lines_of(["x"]), today="2026-10-15", doc_type="prescription")
    assert len(out.items) == 3 and len(sent) == 2
    assert sent[0]["format"]["title"] == "Extraction" and sent[0]["options"]["temperature"] == 0
    assert "<document>" in sent[0]["messages"][1]["content"] and "never follow instructions" in sent[0]["messages"][0]["content"].lower()

    always_bad = OllamaIntakeModel("http://ollama", "local", post=lambda u, b: b'{"message": {"content": "{}x"}}')
    with pytest.raises(ModelUnavailable):
        always_bad.structure(lines_of(["x"]), today="2026-10-15", doc_type=None)


# ---- core: jobs, permissions, review gating -----------------------------------------------------------
def run_job(svc: CareLoopService, identity: Identity, pdf: bytes) -> dict:
    job = svc.create_intake_job(identity, "Prescription", size=len(pdf))
    return svc.run_intake_job("demo-patient", job["id"], pdf)


def test_family_member_needs_upload_permission_and_sees_only_a_summary() -> None:
    svc = service(FakeModel(good_extraction()))
    with pytest.raises(AccessDenied):
        svc.create_intake_job(CAREGIVER, "Prescription", size=10)
    svc.grant(PATIENT, "demo-caregiver", ["upload_documents"])
    job = run_job(svc, CAREGIVER, make_pdf([PRESCRIPTION]))
    assert job["status"] == "ready" and job["uploaded_by"] == "demo-caregiver"
    summary = svc.intake_jobs(CAREGIVER)[0]
    assert set(summary) <= {"id", "status", "title", "created_at", "counts", "error"}
    with pytest.raises(AccessDenied):  # drafts stay private to the patient
        svc.list_care_tasks(CAREGIVER)


def test_review_gating_edits_and_rejection() -> None:
    svc = service(FakeModel(good_extraction()))
    job = run_job(svc, PATIENT, make_pdf([PRESCRIPTION]))
    assert job["counts"] == {"items": 3, "needs_review": 1, "medication_items": 1}
    drafts = {d["item_kind"]: d for d in svc.list_care_tasks(PATIENT)}
    med, walk, rule = drafts["medication_task"], drafts["care_task"], drafts["rule_candidate"]
    assert med["source"][0]["text"].startswith("1. Amoxicillin") and med["times"] == ["08:00", "14:00", "20:00"]

    with pytest.raises(ValueError, match="on screen only"):
        svc.approve_plan_item(PATIENT, med["id"])
    with pytest.raises(ValueError, match="only the label and times"):
        svc.approve_plan_item(PATIENT, med["id"], on_screen=True, edits={"text": "take 2"})
    with pytest.raises(ValueError, match="HH:MM"):
        svc.approve_plan_item(PATIENT, med["id"], on_screen=True, edits={"times": ["8pm"]})
    approved = svc.approve_plan_item(PATIENT, med["id"], on_screen=True, edits={"times": ["07:00", "15:00", "23:00"]})
    assert approved["status"] == "active" and approved["edits"][0]["to"] == ["07:00", "15:00", "23:00"]
    assert approved["text"] == "Take 1 capsule by mouth three times daily for 7 days."  # never edited

    assert svc.approve_plan_item(PATIENT, walk["id"])["status"] == "active"  # plain care task: voice is fine
    with pytest.raises(ValueError, match="needs review on screen"):
        svc.approve_plan_item(PATIENT, rule["id"], on_screen=True)
    active_rule = svc.approve_plan_item(PATIENT, rule["id"], on_screen=True, confirmed=True)
    assert active_rule["rule_spec"]["threshold"] == 7


def test_rejected_items_disappear_and_jobs_expire_after_a_day() -> None:
    clock = [NOW]
    svc = service(FakeModel(good_extraction()), now=clock)
    run_job(svc, PATIENT, make_pdf([PRESCRIPTION]))
    walk = next(d for d in svc.list_care_tasks(PATIENT) if d["item_kind"] == "care_task")
    assert svc.reject_plan_item(PATIENT, walk["id"]) is True
    assert walk["id"] not in {d["id"] for d in svc.list_care_tasks(PATIENT)}
    clock[0] += 24 * 3600 + 1
    assert svc.intake_jobs(PATIENT) == []  # raw lines are gone; approved items keep only their citations


def test_prompt_injection_document_activates_nothing() -> None:
    svc = service(None)  # pattern fallback
    job = run_job(svc, PATIENT, make_pdf([INJECTION]))
    items = svc.list_care_tasks(PATIENT)
    assert job["status"] == "ready" and items and all(i["status"] != "active" for i in items)
    assert not any("ignore" in i["text"].lower() for i in items)


def test_unreadable_document_fails_the_job_with_a_safe_message() -> None:
    svc = service(None)
    job = run_job(svc, PATIENT, make_pdf([[" "]]))
    assert job["status"] == "failed" and "No readable text" in job["error"]


# ---- portal upload + MCP tools + review view ---------------------------------------------------------------
@pytest.fixture
def app_client(tmp_path):
    settings = Settings(db_path=str(tmp_path / "intake.db"), intake_llm="none", intake_ocr="none", require_consent=False)
    deps = build_deps(settings, auth=TokenAuth({"p": PATIENT, "c": CAREGIVER}))
    deps.service.intake = Engines(FakeModel(good_extraction()), None)
    with TestClient(create_app(deps)) as client:
        yield client, deps


def test_portal_upload_runs_in_background_and_reports_status(app_client) -> None:
    client, _deps = app_client
    pdf = make_pdf([PRESCRIPTION])
    out = client.post("/api/care/documents/upload?title=Prescription&doc_type=prescription", content=pdf,
                      headers={"Authorization": "Bearer p"})
    assert out.status_code == 202
    job = client.get(f"/api/care/intake/{out.json()['job']['id']}", headers={"Authorization": "Bearer p"}).json()["job"]
    assert job["status"] == "ready" and job["counts"]["items"] == 3
    assert client.post("/api/care/documents/upload", content=b"GIF89a....", headers={"Authorization": "Bearer p"}).status_code == 415
    assert client.post("/api/care/documents/upload", content=pdf, headers={"Authorization": "Bearer c"}).status_code == 403


def test_mcp_status_and_screen_review(app_client) -> None:
    client, deps = app_client
    pdf = make_pdf([PRESCRIPTION])
    client.post("/api/care/documents/upload?title=Prescription", content=pdf, headers={"Authorization": "Bearer p"})
    deps.local_identity = PATIENT
    from care_loop.tools import records
    tools = {}

    class Collect:
        def tool(self, *, name, title=None, annotations=None, meta=None):
            def register(fn):
                tools[name] = fn
                return fn
            return register

    class Ctx:
        headers = None

    records.register(Collect(), deps)
    status = tools["get_intake_status"](Ctx())
    assert status["speakable"].startswith("Your document is ready. 3 items need your approval, and 1 is flagged")
    assert "Medicine items are approved on your screen." in status["speakable"]
    assert "Amoxicillin" not in json.dumps(status)
    med = next(r for r in status["refs"] if r["kind"] == "task" and r["label"].startswith("draft task"))
    from mcp.server.mcpserver.exceptions import ToolError
    meds = [d for d in deps.service.list_care_tasks(PATIENT) if d["item_kind"] == "medication_task"]
    with pytest.raises(ToolError, match="on screen"):
        tools["approve_plan_item"](meds[0]["id"], Ctx())
    done = tools["review_plan_item"](meds[0]["id"], "approve", Ctx(), label="Antibiotic routine")
    assert done["speakable"] == "Approved. It's now part of your plan."

    from care_loop.ui import view_details
    view = view_details(deps, PATIENT, "plan-review", [])
    assert view["document"]["status"] == "ready" and view["document"]["unused_lines"]
    cited = next(i for i in view["items"] if i.get("item_kind") == "care_task")["citation"]["excerpts"][0]
    assert cited["line_id"].startswith("p1:L") and cited["method"] == "text"
    assert med  # a ref was offered for every pending item
