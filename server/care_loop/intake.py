"""Deterministic, local-only intake for the synthetic CareLoop demo.

This is deliberately a very small grammar, rather than a clinical language
parser.  Anything outside it is retained only as a short source excerpt and is
flagged for manual review; it never becomes an active instruction.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

MAX_TEXT_BYTES = 24 * 1024
MAX_PAGES = 20
MAX_EXCERPT_CHARS = 500
_DIRECTIVE = re.compile(r"^\s*(TASK|RULE)\s*:\s*(.+?)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class Draft:
    kind: str
    text: str
    page: int
    schedule: str | None = None


@dataclass(frozen=True)
class IntakeResult:
    source_hash: str
    excerpts: list[dict[str, object]]
    drafts: list[Draft]
    manual_review_reasons: list[str]


def extract_text_fixture(text: str) -> IntakeResult:
    """Extract only explicitly tagged fixture statements from plain text.

    ``TASK: … | schedule: …`` and ``RULE: …`` are accepted.  The text is not
    persisted wholesale; callers receive only the cited directive snippets.
    Form-feed characters delimit synthetic pages.
    """
    encoded = text.encode("utf-8")
    if not text.strip():
        raise ValueError("document text is required")
    if len(encoded) > MAX_TEXT_BYTES:
        raise ValueError("document text exceeds the intake limit")
    pages = text.split("\f")
    if len(pages) > MAX_PAGES:
        raise ValueError("document exceeds the page limit")

    drafts: list[Draft] = []
    excerpts: list[dict[str, object]] = []
    reasons: list[str] = []
    for number, page_text in enumerate(pages, start=1):
        found = False
        for line in page_text.splitlines():
            match = _DIRECTIVE.match(line)
            if not match:
                continue
            found = True
            kind, value = match.group(1).upper(), match.group(2).strip()
            if len(value) > MAX_EXCERPT_CHARS:
                reasons.append(f"page {number}: statement is too long for safe review")
                continue
            schedule = None
            if kind == "TASK" and "|" in value:
                task, separator, schedule_part = value.partition("|")
                if not separator or not schedule_part.strip().lower().startswith("schedule:"):
                    reasons.append(f"page {number}: task schedule needs manual review")
                    continue
                value, schedule = task.strip(), schedule_part.strip()[len("schedule:"):].strip()
                if not value or not schedule:
                    reasons.append(f"page {number}: incomplete task statement")
                    continue
            if not value:
                reasons.append(f"page {number}: incomplete {kind.lower()} statement")
                continue
            excerpt = f"{kind}: {match.group(2).strip()}"
            excerpts.append({"page": number, "excerpt": excerpt[:MAX_EXCERPT_CHARS]})
            drafts.append(Draft(kind, value, number, schedule))
        # Free-form clinical prose must not be treated as an extraction result.
        if page_text.strip() and not found:
            reasons.append(f"page {number}: unstructured text requires manual review")

    # Different tagged instructions with the same normalized schedule are not
    # reconciled by code.  Preserve both drafts and require a human decision.
    seen: dict[tuple[str, str], str] = {}
    for draft in drafts:
        # A schedule gives deterministic code a meaningful collision key.
        # Untimed tasks are not assumed to conflict merely because there are
        # two of them.
        if not draft.schedule:
            continue
        key = (draft.kind, draft.schedule.lower())
        earlier = seen.get(key)
        if earlier is not None and earlier.casefold() != draft.text.casefold():
            reasons.append("conflicting extracted instructions require manual review")
        seen[key] = draft.text
    if not drafts:
        reasons.append("no supported TASK or RULE statements were found")
    return IntakeResult(hashlib.sha256(encoded).hexdigest(), excerpts, drafts, list(dict.fromkeys(reasons)))
