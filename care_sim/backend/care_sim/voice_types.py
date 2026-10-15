"""Structured values used by the Ollama-backed CareLoop voice path."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class VoicePlan:
    tool: str | None
    reply: str
    arguments: dict


def pain_score(text: str) -> int | None:
    """Extract an explicit 0–10 score without guessing from unrelated numbers."""
    match = re.search(r"\b(10|[0-9])\s*(?:out of|/|on a scale of)\s*10\b", text)
    if match:
        return int(match.group(1))
    match = re.search(r"\bpain(?:\s+(?:score|level|is))?\s*(?:of|at|=)?\s*(10|[0-9])\b", text)
    if match:
        return int(match.group(1))
    words = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
             "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
    match = re.search(r"\b(" + "|".join(words) + r")\s*(?:out of|/|on a scale of)\s*ten\b", text)
    return words[match.group(1)] if match else None
