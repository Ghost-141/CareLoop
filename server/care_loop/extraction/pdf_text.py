"""PDF text-layer extraction with a per-page quality check that decides when OCR is needed."""
from __future__ import annotations

from io import BytesIO


def pdf_page_texts(data: bytes, *, max_pages: int) -> list[str]:
    from . import ExtractionError
    if b"%%EOF" not in data[-2048:]:
        raise ExtractionError("The PDF is incomplete or damaged.")
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # the `intake` extra is not installed
        raise ExtractionError("PDF reading isn't installed (uv sync --extra intake).") from exc
    try:
        reader = PdfReader(BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise ExtractionError("Password-protected PDFs aren't supported.")
        if not reader.pages:
            raise ExtractionError("The PDF has no pages.")
        if len(reader.pages) > max_pages:
            raise ExtractionError(f"The PDF has more than {max_pages} pages.")
        return [page.extract_text() or "" for page in reader.pages]
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError("The PDF could not be read safely.") from exc


def page_needs_ocr(text: str) -> bool:
    """True when the text layer is missing or unusable (scan, broken font map)."""
    compact = "".join(text.split())
    if len(compact) < 20:
        return True
    if text.count("�") > len(compact) * 0.05:
        return True
    readable = sum(ch.isalnum() or ch in ".,:;()/-%+'\"#&" for ch in compact)
    if readable / len(compact) < 0.6:
        return True
    # A broken font map often yields single characters separated by spaces.
    words = text.split()
    single = sum(len(word) == 1 for word in words)
    return len(words) > 20 and single / len(words) > 0.6
