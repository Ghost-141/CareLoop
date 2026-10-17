"""Turn extracted lines into verified draft items: model proposal → deterministic checks."""
from __future__ import annotations

from datetime import UTC, datetime

from ..extraction import ExtractedDocument
from .model import IntakeModel, ModelUnavailable, OllamaIntakeModel, OpenAIIntakeModel
from .validate import StructuredDocument, ValidatedItem, command_like_lines, pattern_extraction, validate


def structure_document(doc: ExtractedDocument, model: IntakeModel | None, *, now: float,
                       doc_type: str | None = None) -> StructuredDocument:
    today = datetime.fromtimestamp(now, UTC).date().isoformat()
    notes = list(doc.notes)
    # Lines that read like commands to an AI are set aside: the model never sees them and no item can cite them.
    set_aside = command_like_lines(doc.lines)
    skipped = {line.id for line in set_aside}
    lines = [line for line in doc.lines if line.id not in skipped]
    notes += [f"Line {line.id} reads like an instruction to an AI assistant, not a care instruction, so it was ignored."
              for line in set_aside]
    if model is not None:
        try:
            proposed = model.structure(lines, today=today, doc_type=doc_type)
            # Even if a model cites a withheld line anyway, nothing built on it survives.
            proposed.items = [item for item in proposed.items if not skipped & set(item.source_lines)]
            proposed.follow_up_lines = [line_id for line_id in proposed.follow_up_lines if line_id not in skipped]
            result = validate(proposed, lines, engine=model.name)
            result.notes = notes
            result.unused_lines += [line.as_record() for line in set_aside]
            return result
        except ModelUnavailable as exc:
            notes.append(f"{exc} Items were found by pattern matching instead; check each one.")
    result = validate(pattern_extraction(lines), lines, engine="patterns")
    for item in result.items:  # pattern-found items always get a human look
        item.status = "needs_review"
    result.notes = notes
    result.unused_lines += [line.as_record() for line in set_aside]
    return result


__all__ = ["IntakeModel", "ModelUnavailable", "OllamaIntakeModel", "OpenAIIntakeModel", "StructuredDocument", "ValidatedItem",
           "structure_document"]
