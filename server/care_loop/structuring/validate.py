"""Deterministic checks on the model's proposal, plus a pattern-based fallback.

The model proposes; this module verifies. An item that fails a check is kept but
marked ``needs_review`` with the reason, so nothing is dropped and nothing
unverified becomes active without a person looking at it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..extraction.lines import SourceLine
from .schema import Extraction, ExtractedItem, Medication, RuleCandidate, Schedule

# ---- schedule table ---------------------------------------------------------------------
# Order matters: specific phrases before generic "daily".
_FREQUENCIES: list[tuple[str, str]] = [
    # "As needed" wins: a PRN medicine gets no fixed dose times, even with an interval.
    (r"\bas\s+needed\b|\bp\.?r\.?n\.?\b|\bwhen\s+required\b|\bif\s+needed\b", "as_needed"),
    (r"\bevery\s*12\s*(?:hours|hrs?|h)\b|\bq\s*12\s*h\b", "twice_daily"),
    (r"\bevery\s*8\s*(?:hours|hrs?|h)\b|\bq\s*8\s*h\b", "three_times_daily"),
    (r"\bevery\s*6\s*(?:hours|hrs?|h)\b|\bq\s*6\s*h\b", "four_times_daily"),
    (r"\bevery\s*\d+\s*(?:hours|hrs?|h)\b|\bq\s*\d+\s*h\b", "every_n_hours"),
    (r"\b(?:four|4)\s*times\s*(?:a|per|each)?\s*(?:day|daily)\b|\bq\.?i\.?d\.?\b", "four_times_daily"),
    (r"\b(?:three|3)\s*times\s*(?:a|per|each)?\s*(?:day|daily)\b|\bthrice\s+(?:a\s+day|daily)\b|\bt\.?i\.?d\.?\b", "three_times_daily"),
    (r"\b(?:twice|two\s*times|2\s*times)\s*(?:a|per|each)?\s*(?:day|daily)\b|\bb\.?i\.?d\.?\b", "twice_daily"),
    (r"\bat\s+bedtime\b|\bat\s+night\b|\bnightly\b|\bh\.?s\.?\b", "at_bedtime"),
    (r"\b(?:once\s*(?:a\s*)?week(?:ly)?|weekly)\b", "weekly"),
    (r"\b(?:once\s*(?:a\s*)?day|once\s+daily|every\s+(?:day|morning|evening|afternoon)|daily|o\.?d\.?|q\.?d\.?)\b", "once_daily"),
]
_TIME_OF_DAY = [(r"\bbefore\s+breakfast\b", "07:30"), (r"\bmorning\b|\bbreakfast\b", "08:00"),
                (r"\bnoon\b|\blunch", "12:00"), (r"\bafternoon\b", "14:00"),
                (r"\bevening\b|\bdinner\b|\bsupper\b", "19:00")]
DEFAULT_TIMES = {
    "once_daily": ["08:00"], "twice_daily": ["08:00", "20:00"], "three_times_daily": ["08:00", "14:00", "20:00"],
    "four_times_daily": ["08:00", "12:00", "16:00", "20:00"], "at_bedtime": ["21:00"], "weekly": ["09:00"],
}
_CLOCK = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)\b|\b([01]?\d|2[0-3]):([0-5]\d)\b", re.IGNORECASE)
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_WORD_NUMBERS = {w: str(i) for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve".split())} | {"half": "0.5"}


def detect_frequency(text: str) -> str | None:
    lowered = text.lower()
    for pattern, frequency in _FREQUENCIES:
        if re.search(pattern, lowered):
            return frequency
    return None


def clock_times(text: str) -> list[str]:
    times = []
    for match in _CLOCK.finditer(text):
        if match.group(3):
            hour, minute = int(match.group(1)) % 12, int(match.group(2) or 0)
            if match.group(3).lower().startswith("p"):
                hour += 12
        else:
            hour, minute = int(match.group(4)), int(match.group(5))
        if hour < 24 and minute < 60:
            times.append(f"{hour:02d}:{minute:02d}")
    return list(dict.fromkeys(times))


def suggested_times(frequency: str | None, text: str) -> list[str]:
    """Explicit clock times in the text win, then a once-a-day time of day, then the table. Always editable."""
    if frequency == "as_needed":
        return []
    explicit = clock_times(text)
    if explicit:
        return explicit
    if frequency == "once_daily":
        for pattern, time in _TIME_OF_DAY:
            if re.search(pattern, text.lower()):
                return [time]
    return DEFAULT_TIMES.get(frequency or "", [])


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w.%/]+", " ", text.casefold()).split())


def _numbers(text: str) -> set[str]:
    found = {n.rstrip("0").rstrip(".") if "." in n else n for n in _NUMBER.findall(text)}
    for word in re.findall(r"[a-z]+", text.lower()):
        if word in _WORD_NUMBERS:
            found.add(_WORD_NUMBERS[word])
    return found


# ---- validated output ----------------------------------------------------------------------
@dataclass
class ValidatedItem:
    kind: str
    label: str
    instruction: str
    source: list[dict[str, Any]]
    status: str  # "draft" | "needs_review"
    reasons: list[str] = field(default_factory=list)
    medication: dict[str, Any] | None = None
    frequency: str | None = None
    times: list[str] = field(default_factory=list)
    interval_hours: int | None = None
    duration_days: int | None = None
    suggested_assignee: str = "unspecified"
    rule_spec: dict[str, Any] | None = None

    @property
    def record_type(self) -> str:
        if self.kind in {"medication_task", "care_task"}:
            return "PLAN_TASK"
        if self.rule_spec is not None:
            return "PLAN_RULE"
        return "PLAN_NOTE"


@dataclass
class StructuredDocument:
    items: list[ValidatedItem]
    unused_lines: list[dict[str, Any]]
    follow_up_date: str | None
    engine: str  # model name or "patterns"
    notes: list[str] = field(default_factory=list)


def validate(extraction: Extraction, lines: list[SourceLine], *, engine: str) -> StructuredDocument:
    by_id = {line.id: line for line in lines}
    items: list[ValidatedItem] = []
    cited: set[str] = set()
    medication_count = 0
    for proposal in extraction.items:
        reasons: list[str] = []
        known = [line_id for line_id in proposal.source_lines if line_id in by_id]
        if len(known) != len(proposal.source_lines):
            reasons.append("cites lines that aren't in the document")
        cited.update(known)
        source = [by_id[line_id] for line_id in known]
        source_text = " ".join(line.text for line in source)

        # 1. The instruction must be in the cited lines.
        if not source or _norm(proposal.instruction_verbatim) not in _norm(source_text):
            reasons.append("the instruction doesn't match the cited text")

        # 2. Every number the model reports must appear in the cited lines.
        source_numbers = _numbers(source_text)
        reported = [proposal.instruction_verbatim]
        if proposal.medication:
            reported += [v for v in proposal.medication.model_dump().values() if v]
        if proposal.schedule:
            reported += [str(v) for v in (proposal.schedule.interval_hours, proposal.schedule.duration_days) if v is not None]
        if proposal.rule:
            reported += [str(proposal.rule.threshold), str(proposal.rule.consecutive_days)]
        invented = sorted(_numbers(" ".join(reported)) - source_numbers)
        if invented:
            reasons.append(f"number not in the source: {', '.join(invented)}")

        # Medicine names must be written in the source too.
        medication = proposal.medication.model_dump() if proposal.medication else None
        if proposal.kind == "medication_task":
            if not medication or not medication.get("name"):
                reasons.append("medicine name not identified")
            elif _norm(medication["name"]) not in _norm(source_text):
                reasons.append("medicine name not found in the cited text")

        # 3. Schedule: deterministic detection is the reference.
        detected = detect_frequency(proposal.instruction_verbatim) or detect_frequency(source_text)
        frequency = proposal.schedule.frequency if proposal.schedule else "unspecified"
        if detected and frequency not in {"unspecified", detected}:
            reasons.append(f"frequency looks like {detected.replace('_', ' ')}, not {frequency.replace('_', ' ')}")
        frequency = detected or (None if frequency == "unspecified" else frequency)
        times = suggested_times(frequency, proposal.instruction_verbatim) if proposal.kind in {"medication_task", "care_task"} else []

        # 4. Alert rules: only the supported spec, numbers from the source, confirmed by the patient.
        rule_spec = None
        kind = proposal.kind
        stated = _PAIN_RULE.search(proposal.instruction_verbatim)
        if kind in {"warning_sign", "note", "rule_candidate"} and stated:
            # Safety net: the rule's own wording is recognised by a fixed pattern and its
            # numbers come from the text, not from the model.
            kind = "rule_candidate"
            proposal = proposal.model_copy(update={"rule": RuleCandidate(
                threshold=int(stated.group(1)), consecutive_days=int(stated.group(2)))})
        if kind == "rule_candidate":
            rule = proposal.rule
            if (rule and "pain" in source_text.lower() and 0 <= rule.threshold <= 10 and 1 <= rule.consecutive_days <= 31
                    and str(rule.threshold) in source_numbers and str(rule.consecutive_days) in source_numbers):
                rule_spec = {"kind": "pain_score_at_or_above", "threshold": rule.threshold,
                             "consecutive_days": rule.consecutive_days}
                reasons.append("confirm this alert rule matches your clinician's words")
            else:
                kind = "warning_sign"  # shown to the patient; never triggers alerts

        # 5. Low-confidence OCR forces review.
        if any(line.low_confidence for line in source):
            reasons.append("part of this was read by OCR with low confidence")

        reasons += [f"model note: {u}" for u in proposal.uncertainties[:3]]

        label = " ".join(proposal.label.split())[:60] or "Care item"
        if kind == "medication_task":
            medication_count += 1
            label = f"Medicine routine {medication_count}"  # never a drug name on a speaker
        items.append(ValidatedItem(
            kind=kind, label=label, instruction=proposal.instruction_verbatim.strip()[:500],
            source=[line.as_record() for line in source], status="needs_review" if reasons else "draft",
            reasons=list(dict.fromkeys(reasons)), medication=medication if kind == "medication_task" else None,
            frequency=frequency, times=times,
            interval_hours=proposal.schedule.interval_hours if proposal.schedule else None,
            duration_days=proposal.schedule.duration_days if proposal.schedule else None,
            suggested_assignee=proposal.suggested_assignee, rule_spec=rule_spec))

    # 7. Conflicts: the same medicine with different instructions.
    by_name: dict[str, list[ValidatedItem]] = {}
    for item in items:
        if item.medication and item.medication.get("name"):
            by_name.setdefault(_norm(item.medication["name"]), []).append(item)
    for group in by_name.values():
        if len({_norm(i.instruction) for i in group}) > 1:
            for item in group:
                item.status = "needs_review"
                item.reasons.append("another line gives a different instruction for the same medicine")

    cited.update(line_id for line_id in extraction.follow_up_lines if line_id in by_id)
    # 6. Coverage: every line is either used or listed for the reviewer.
    unused = [line.as_record() for line in lines if line.id not in cited]
    return StructuredDocument(items, unused, extraction.follow_up_date, engine)


# ---- lines that are commands to an AI, not care instructions --------------------------------------
# A document is untrusted data. Whatever model reads it, these lines never reach it and can never
# become items; the reviewer is told they were set aside.
_AI_COMMANDS = [re.compile(p, re.I) for p in (
    r"\b(ignore|disregard|forget|override)\b.{0,50}\b(previous|prior|above|earlier|all|your)\b.{0,40}\b(instructions?|prompts?|rules?|guidelines?)\b",
    r"^\s*(system|assistant|developer|admin)\s*(prompt|message)?\s*:",
    r"\b(mark|set|make)\b.{0,30}\b(every|all|each)\b.{0,25}\b(items?|tasks?|rules?)\b.{0,25}\b(approved|active|done|complete)",
    r"\b(reveal|print|repeat|show)\b.{0,30}\b(system|hidden)\b.{0,15}\b(prompt|instructions?)\b",
    r"\b(you are now|act as|pretend to be)\b.{0,40}\b(ai|assistant|model|llm|chatbot)\b",
)]


def command_like_lines(lines: list[SourceLine]) -> list[SourceLine]:
    return [line for line in lines if any(p.search(line.text) for p in _AI_COMMANDS)]


# ---- deterministic fallback (no model) ------------------------------------------------------------
_MEDICINE_HINT = re.compile(r"\b(\d+\s*(mg|mcg|g|ml|units?)|tablets?|tabs?|capsules?|caps?|drops?|puffs?|syrup|injection)\b", re.I)
_WARNING_HINT = re.compile(r"\b(call|contact|seek|go to|return to)\b.*\b(if|when)\b|\bemergency\b", re.I)
_APPOINTMENT_HINT = re.compile(r"\b(follow[- ]?up|appointment|review)\b.*\b(on|in|date)\b", re.I)
_PAIN_RULE = re.compile(r"pain[^.]*?(\d{1,2})\s*(?:/\s*10)?\s*(?:or\s+(?:higher|more|above)|\+)[^.]*?(\d{1,2})\s*(?:consecutive\s+)?days", re.I)


def pattern_extraction(lines: list[SourceLine]) -> Extraction:
    """A conservative line-by-line extraction used when the model is unavailable."""
    items: list[ExtractedItem] = []
    for line in lines:
        text = line.text
        rule = _PAIN_RULE.search(text)
        if rule:
            items.append(ExtractedItem(kind="rule_candidate", label="Pain follow-up rule", instruction_verbatim=text,
                                       source_lines=[line.id], rule=RuleCandidate(threshold=int(rule.group(1)),
                                                                                  consecutive_days=int(rule.group(2)))))
        elif _WARNING_HINT.search(text):
            items.append(ExtractedItem(kind="warning_sign", label="When to get help", instruction_verbatim=text,
                                       source_lines=[line.id]))
        elif _APPOINTMENT_HINT.search(text):
            items.append(ExtractedItem(kind="appointment", label="Follow-up visit", instruction_verbatim=text,
                                       source_lines=[line.id]))
        elif detect_frequency(text):
            medicine = bool(_MEDICINE_HINT.search(text))
            name = text.split()[0].strip(",:;") if medicine else None
            items.append(ExtractedItem(
                kind="medication_task" if medicine else "care_task", label="Care task", instruction_verbatim=text,
                source_lines=[line.id], medication=Medication(name=name) if medicine else None,
                schedule=Schedule(frequency=detect_frequency(text)),
                uncertainties=["found by pattern matching, not read by the model"]))
    return Extraction(items=items)
