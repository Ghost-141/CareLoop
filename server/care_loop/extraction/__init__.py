"""Document text extraction: the PDF text layer first, OCR only for pages without usable text.

The output is a list of numbered :class:`SourceLine` objects (``p1:L12``) that every later
stage cites. Nothing here interprets the text.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from .lines import SourceLine, split_lines
from .pdf_text import page_needs_ocr, pdf_page_texts

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_PAGES = 20
PDF, PNG, JPEG = "application/pdf", "image/png", "image/jpeg"


class ExtractionError(ValueError):
    """The document can't be read safely; the message is generic and safe to show."""


@dataclass
class ExtractedDocument:
    source_hash: str
    lines: list[SourceLine]
    page_methods: dict[int, str] = field(default_factory=dict)  # page -> "text" | "ocr" | "empty"
    notes: list[str] = field(default_factory=list)

    @property
    def used_ocr(self) -> bool:
        return "ocr" in self.page_methods.values()


def sniff(data: bytes) -> str:
    if data.startswith(b"%PDF-"):
        return PDF
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    if data[:3] == b"\xff\xd8\xff":
        return JPEG
    raise ExtractionError("Only PDF, PNG or JPEG documents are supported.")


def extract_document(data: bytes, ocr=None) -> ExtractedDocument:
    """Extract numbered lines. ``ocr`` is an OCR engine (see ``ocr.py``) or None."""
    if not data:
        raise ExtractionError("The document is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ExtractionError("The document is larger than 5 MB.")
    kind = sniff(data)
    digest = hashlib.sha256(data).hexdigest()
    if kind != PDF:
        if ocr is None:
            raise ExtractionError("Photos need OCR, which isn't installed. Upload a typed PDF instead.")
        lines = ocr.read_image(data, page=1)
        return ExtractedDocument(digest, lines, {1: "ocr" if lines else "empty"})

    texts = pdf_page_texts(data, max_pages=MAX_PAGES)
    doc = ExtractedDocument(digest, [])
    for number, text in enumerate(texts, start=1):
        if not page_needs_ocr(text):
            doc.lines.extend(split_lines(text, page=number, method="text"))
            doc.page_methods[number] = "text"
            continue
        if ocr is None:
            doc.page_methods[number] = "empty"
            doc.notes.append(f"Page {number} has no readable text and OCR isn't installed; it needs manual review.")
            continue
        lines = ocr.read_pdf_page(data, page=number)
        doc.lines.extend(lines)
        doc.page_methods[number] = "ocr" if lines else "empty"
        if not lines:
            doc.notes.append(f"Page {number} could not be read, even with OCR; it needs manual review.")
    if not doc.lines:
        raise ExtractionError("No readable text was found in this document.")
    return doc


__all__ = ["ExtractedDocument", "ExtractionError", "SourceLine", "extract_document", "sniff", "MAX_UPLOAD_BYTES"]
