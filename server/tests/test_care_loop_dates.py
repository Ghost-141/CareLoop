"""A visit date is read only when the text names exactly one unambiguous date. CareLoop never guesses."""
import pytest

from care_loop.structuring.dates import parse_unambiguous_date
from care_loop.structuring.schema import Extraction, ExtractedItem
from test_care_loop_document_intake import PATIENT, FakeModel, good_extraction, make_pdf, PRESCRIPTION, run_job, service


@pytest.mark.parametrize("text, expected", [
    ("Follow-up appointment on 2026-10-24 at Riverside Family Clinic.", "2026-10-24"),
    ("See Dr Rahman on October 24, 2026.", "2026-10-24"),
    ("See Dr Rahman on October 24 2026", "2026-10-24"),
    ("Review on Oct 24th, 2026 at 9 AM", "2026-10-24"),
    ("Review on 24 October 2026", "2026-10-24"),
    ("Review on 24th of Oct. 2026", "2026-10-24"),
    ("Visit 2026-02-28 and again on 28 February 2026", "2026-02-28"),  # the same date twice is still one date
])
def test_one_clear_date_is_read(text, expected) -> None:
    assert parse_unambiguous_date(text) == expected


@pytest.mark.parametrize("text", [
    "Follow up on 10/11",                         # October 11 or November 10?
    "Follow up on 10/11/2026",                    # same ambiguity, even with a year
    "Follow up on October 24",                    # no year
    "Follow up next Tuesday",
    "Follow up in 2 weeks",
    "Follow up from 2026-10-01 to 2026-10-05",    # two different dates
    "Review Oct 1, 2026 or Oct 8, 2026",
    "Follow up on 2026-13-40",                    # not a real date
    "Follow up on February 30, 2026",             # not a real date
    "Dose 20260101 morning",                      # not a date
    "", None,
])
def test_anything_unclear_gives_no_date(text) -> None:
    assert parse_unambiguous_date(text) is None


def _appointment_job(lines, line_id, text):
    extraction = Extraction(items=[ExtractedItem(kind="appointment", label="Follow-up visit", source_lines=[line_id],
                                                  instruction_verbatim=text)])
    svc = service(FakeModel(extraction))
    run_job(svc, PATIENT, make_pdf([lines]))
    return [i for i in svc.list_care_tasks(PATIENT) if i.get("item_kind") == "appointment"]


def test_an_appointment_item_carries_its_visit_date_on_the_plan_item() -> None:
    """The date is kept on the item, so it survives the 24-hour intake job."""
    text = "Follow-up appointment on 2026-10-24 at Riverside Family Clinic."
    visits = _appointment_job(PRESCRIPTION, "p1:L13", text)
    assert len(visits) == 1 and visits[0].get("due_date") == "2026-10-24" and visits[0]["text"] == text


def test_an_ambiguous_date_leaves_the_item_without_a_date() -> None:
    text = "Follow-up appointment on 10/11 at the clinic."
    visits = _appointment_job([text], "p1:L1", text)
    assert len(visits) == 1 and "due_date" not in visits[0]  # still a usable item, just undated
