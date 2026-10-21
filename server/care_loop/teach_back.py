"""Teach-back: ask the patient to say back a key value from their approved plan, and check it in code.

The questions come from the approved, cited item's own fields. The answer arrives as the person's
words; this module turns them into one structured value and compares it with the plan. Nothing here
explains, advises or interprets a symptom: a miss is answered by reading the plan back.
"""
from __future__ import annotations

import re
from typing import Any

from .structuring.validate import detect_frequency

# Hours between doses for each daily frequency: "three times a day" and "every 8 hours" are the same answer.
_INTERVALS = {"once_daily": 24.0, "at_bedtime": 24.0, "twice_daily": 12.0, "three_times_daily": 8.0, "four_times_daily": 6.0}
_WORDS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve".split())}
_PERIODS = {"morning": (5, 12), "afternoon": (12, 17), "evening": (17, 21), "night": (21, 29)}
_PERIOD_WORDS = [(r"\b(morning|breakfast|a\.?m\.?)\b", "morning"), (r"\b(afternoon|lunch|midday|noon)\b", "afternoon"),
                 (r"\b(evening|dinner|supper)\b", "evening"), (r"\b(night|bedtime|bed|tonight)\b", "night")]
_STOP = re.compile(r"^\W*(stop|pause|enough|that'?s (enough|all)|done for now|cancel)\b", re.IGNORECASE)
_DONT_KNOW = re.compile(r"\b(don'?t know|do not know|not sure|no idea|can'?t remember|cannot remember|forgot|dunno)\b",
                        re.IGNORECASE)
_AS_NEEDED = re.compile(r"\b(as needed|when(ever)? (i|you) (need|want)|only when|if (i|you) need|if needed|"
                        r"when (it|the pain|i'?m in pain) (hurts|is bad)|p\.?r\.?n\.?)\b", re.IGNORECASE)
_SET_TIMES = re.compile(r"\b(set times?|every day|daily|regular(ly)?|same times?|on a schedule|scheduled)\b", re.IGNORECASE)
_TEMPERATURE = re.compile(r"\b(fever|temperature)\b", re.IGNORECASE)
_NUMBER = re.compile(r"\d+(?:\.\d+)?")

MEDICINE_KINDS = frozenset({"medication_task"})


def is_stop(text: str) -> bool:
    return bool(_STOP.search(text or ""))


def is_dont_know(text: str) -> bool:
    return bool(_DONT_KNOW.search(text or ""))


def _name(item: dict[str, Any]) -> str:
    """What the patient calls the medicine: its name as written, or the spoken label."""
    name = ((item.get("medication") or {}).get("name") or "").strip()
    if not re.search(r"[A-Za-z]{3}", name):  # never "1." from a numbered list
        name = item.get("label") or "this medicine"
    return name.strip()


medicine_name = _name


def period_named(text: str) -> str | None:
    """The part of the day a phrase names: "before breakfast" → "morning", "dinner" → "evening"."""
    return next((p for pattern, p in _PERIOD_WORDS if re.search(pattern, (text or "").lower())), None)


def in_period(clock: str, period: str) -> bool:
    """Whether a "HH:MM" time falls in that part of the day (night runs past midnight)."""
    try:
        hour = int(clock.split(":")[0])
    except ValueError:
        return False
    start, end = _PERIODS[period]
    return start <= (hour + 24 if hour < 5 else hour) < end


def _interval(item: dict[str, Any]) -> float | None:
    if item.get("frequency") == "every_n_hours" and item.get("interval_hours"):
        return float(item["interval_hours"])
    return _INTERVALS.get(item.get("frequency") or "")


def _numbers(text: str) -> list[str]:
    return _NUMBER.findall(text or "")


def checks_for(item: dict[str, Any]) -> list[str]:
    """Which values of this approved item can be checked. An empty list means it is never asked."""
    if item.get("status") != "active":
        return []
    if item["type"] == "PLAN_RULE":
        return ["threshold", "days"] if item.get("rule_spec") else []
    if item["type"] == "PLAN_TASK" and item.get("item_kind") in MEDICINE_KINDS:
        if item.get("frequency") == "as_needed":
            return ["as_needed"]
        if item.get("frequency") in {"once_daily", "at_bedtime"} and len(item.get("times") or []) == 1:
            return ["time"]
        return ["frequency"] if _interval(item) else []
    if item["type"] == "PLAN_NOTE" and item.get("item_kind") == "warning_sign":
        text = str(item.get("text") or "")
        return ["number"] if _TEMPERATURE.search(text) and len(_numbers(text)) == 1 else []
    return []


def question_for(item: dict[str, Any], check: str) -> str:
    name = _name(item)
    return {
        "time": f"When do you take {name}?",
        "frequency": f"How often do you take {name}?",
        "as_needed": f"Do you take {name} at set times, or only when you need it?",
        "threshold": "Your plan has an alert rule for pain. At what pain score does it start?",
        "days": "For how many days in a row?",
        "number": "At what temperature does your plan say to get help?",
    }[check]


def expected_for(item: dict[str, Any], check: str) -> dict[str, Any]:
    """The value the plan holds, read from the approved item's own fields."""
    if check == "time":
        return {"time": item["times"][0]}
    if check == "frequency":
        return {"every_hours": _interval(item)}
    if check == "as_needed":
        return {"as_needed": True}
    if check == "threshold":
        return {"number": float(item["rule_spec"]["threshold"])}
    if check == "days":
        return {"number": float(item["rule_spec"]["consecutive_days"])}
    if check == "number":
        return {"number": float(_numbers(str(item.get("text") or ""))[0])}
    raise ValueError("unknown check")


def _first_number(text: str) -> float | None:
    found = _numbers(text)
    if found:
        return float(found[0])
    word = next((w for w in re.findall(r"[a-z]+", text.lower()) if w in _WORDS), None)
    return float(_WORDS[word]) if word is not None else None


def _times(text: str, expected: str) -> list[str]:
    """Clock times in a spoken answer. A bare hour takes am or pm from a period word, else from the plan's time."""
    lowered = " ".join(text.lower().split())
    for word, number in _WORDS.items():
        lowered = re.sub(rf"\b{word}\b", str(number), lowered)
    period = next((p for pattern, p in _PERIOD_WORDS if re.search(pattern, lowered)), None)
    found = []
    for match in re.finditer(r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?(?![\d:])", lowered):
        hour, minute, meridiem = int(match.group(1)), int(match.group(2) or 0), match.group(3)
        if hour > 23 or minute > 59:
            continue
        if meridiem and 1 <= hour <= 12:
            hour = hour % 12 + (12 if meridiem.startswith("p") else 0)
        elif 1 <= hour <= 12 and period:
            hour = hour % 12 + (12 if period in {"afternoon", "evening", "night"} and hour != 12 else 0)
        elif 1 <= hour <= 12:
            anchor = int(expected[:2])
            hour = min((hour % 12, hour % 12 + 12), key=lambda h: abs(h - anchor))
        found.append(f"{hour:02d}:{minute:02d}")
    return list(dict.fromkeys(found))


def interpret(check: str, text: str, expected: dict[str, Any]) -> dict[str, Any] | None:
    """The one structured value in a spoken answer, or None if there is none. Never the words themselves."""
    text = text or ""
    if check == "time":
        times = _times(text, expected["time"])
        if times:
            return {"times": times}
        lowered = text.lower()
        period = next((p for pattern, p in _PERIOD_WORDS if re.search(pattern, lowered)), None)
        return {"period": period} if period else None
    if check == "frequency":
        if _AS_NEEDED.search(text):
            return {"as_needed": True}
        digits = re.sub(r"\b(" + "|".join(_WORDS) + r")\b", lambda m: str(_WORDS[m.group(1)]), text.lower())
        frequency = detect_frequency(text) or detect_frequency(digits)
        if frequency == "every_n_hours":
            hours = _first_number(digits)
            return {"every_hours": hours} if hours else None
        if frequency in _INTERVALS:
            return {"every_hours": _INTERVALS[frequency]}
        times = _times(text, "12:00")
        if len(times) > 1:  # "8 am, 2 pm and 8 pm" names three doses a day
            return {"every_hours": 24 / len(times)}
        return None
    if check == "as_needed":
        if _AS_NEEDED.search(text):
            return {"as_needed": True}
        if _SET_TIMES.search(text) or detect_frequency(text) not in {None, "as_needed"}:
            return {"as_needed": False}
        return None
    if check in {"threshold", "days", "number"}:
        number = _first_number(text)
        return {"number": number} if number is not None else None
    raise ValueError("unknown check")


def matches(check: str, expected: dict[str, Any], heard: dict[str, Any] | None) -> bool:
    if not heard:
        return False
    if check == "time":
        if "times" in heard:
            return heard["times"] == [expected["time"]]
        low, high = _PERIODS[heard["period"]]
        hour = int(expected["time"][:2])
        return low <= hour < high or low <= hour + 24 < high
    if check == "frequency":
        return heard.get("every_hours") is not None and abs(heard["every_hours"] - expected["every_hours"]) < 1e-6
    if check == "as_needed":
        return heard.get("as_needed") is expected["as_needed"]
    return heard.get("number") is not None and abs(heard["number"] - expected["number"]) < 1e-6
