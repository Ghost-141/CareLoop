"""Read one unambiguous calendar date from the text of a plan item, or nothing.

CareLoop never guesses a date. "10/11" could be October 11 or November 10, so it is not read. A year is
required, and text that names two different dates ("Oct 1 to Oct 5, 2026") is not read either.
"""
from __future__ import annotations

import re
from datetime import date

_MONTHS = {name: number for number, names in enumerate((
    ("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"), ("may",), ("june", "jun"),
    ("july", "jul"), ("august", "aug"), ("september", "sep", "sept"), ("october", "oct"), ("november", "nov"),
    ("december", "dec")), start=1) for name in names}
_MONTH = "|".join(sorted(_MONTHS, key=len, reverse=True))
_ISO = re.compile(r"(?<![\d-])(\d{4})-(\d{2})-(\d{2})(?![\d-])")
_DAY_FIRST = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH})\.?,?\s+(\d{{4}})\b", re.IGNORECASE)
_MONTH_FIRST = re.compile(rf"\b({_MONTH})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.IGNORECASE)


def _valid(year: int, month: int, day: int) -> str | None:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def parse_unambiguous_date(text: str | None) -> str | None:
    """``"2026-10-24"``, ``"October 24, 2026"`` or ``"24 Oct 2026"`` give an ISO date. Anything else gives None."""
    if not text:
        return None
    found: set[str | None] = set()
    for year, month, day in _ISO.findall(text):
        found.add(_valid(int(year), int(month), int(day)))
    for day, month, year in _DAY_FIRST.findall(text):
        found.add(_valid(int(year), _MONTHS[month.lower()], int(day)))
    for month, day, year in _MONTH_FIRST.findall(text):
        found.add(_valid(int(year), _MONTHS[month.lower()], int(day)))
    found.discard(None)
    return found.pop() if len(found) == 1 else None
