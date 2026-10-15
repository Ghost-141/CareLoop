"""Numbered source lines: the unit every extracted item must cite."""
from __future__ import annotations

from dataclasses import dataclass

MAX_LINE_CHARS = 500
LOW_CONFIDENCE_PCT = 85


@dataclass(frozen=True)
class SourceLine:
    page: int
    number: int
    text: str
    method: str  # "text" (PDF text layer) | "ocr"
    confidence_pct: int = 100  # integer percent; storage keeps no floats

    @property
    def id(self) -> str:
        return f"p{self.page}:L{self.number}"

    @property
    def low_confidence(self) -> bool:
        return self.method == "ocr" and self.confidence_pct < LOW_CONFIDENCE_PCT

    def as_record(self) -> dict:
        return {"id": self.id, "page": self.page, "text": self.text, "method": self.method,
                "confidence_pct": self.confidence_pct}


def split_lines(text: str, *, page: int, method: str, start: int = 1) -> list[SourceLine]:
    lines, number = [], start
    for raw in text.splitlines():
        clean = " ".join(raw.split())
        if not clean:
            continue
        lines.append(SourceLine(page, number, clean[:MAX_LINE_CHARS], method))
        number += 1
    return lines
