"""Turn extracted lines into verified draft items: model proposal → deterministic checks."""
from __future__ import annotations

from datetime import UTC, datetime

from ..extraction import ExtractedDocument
from .model import IntakeModel, ModelUnavailable, OllamaIntakeModel
from .validate import StructuredDocument, ValidatedItem, pattern_extraction, validate


def structure_document(doc: ExtractedDocument, model: IntakeModel | None, *, now: float,
                       doc_type: str | None = None) -> StructuredDocument:
    today = datetime.fromtimestamp(now, UTC).date().isoformat()
    notes = list(doc.notes)
    if model is not None:
        try:
            result = validate(model.structure(doc.lines, today=today, doc_type=doc_type), doc.lines, engine=model.name)
            result.notes = notes
            return result
        except ModelUnavailable as exc:
            notes.append(f"{exc} Items were found by pattern matching instead; check each one.")
    result = validate(pattern_extraction(doc.lines), doc.lines, engine="patterns")
    for item in result.items:  # pattern-found items always get a human look
        item.status = "needs_review"
    result.notes = notes
    return result


__all__ = ["IntakeModel", "ModelUnavailable", "OllamaIntakeModel", "StructuredDocument", "ValidatedItem",
           "structure_document"]
