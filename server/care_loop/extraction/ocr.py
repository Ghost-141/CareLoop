"""PaddleOCR fallback for scanned PDF pages and photos.

Pages are rendered with pypdfium2 (pypdf cannot render). Lines keep the OCR
confidence; low-confidence lines force human review later.
"""
from __future__ import annotations

import threading
from io import BytesIO
from typing import Any

from .lines import MAX_LINE_CHARS, SourceLine

RENDER_DPI = 250


class PaddleOcrEngine:
    """Lazy PaddleOCR wrapper. Loading the models is slow, so it happens once."""

    def __init__(self, lang: str = "en") -> None:
        self.lang = lang
        self._engine: Any = None
        self._lock = threading.Lock()

    def _load(self):
        if self._engine is None:
            from paddleocr import PaddleOCR
            # Document photos are usually upright; skip the extra orientation models.
            self._engine = PaddleOCR(lang=self.lang, use_doc_orientation_classify=False,
                                     use_doc_unwarping=False, use_textline_orientation=False)
        return self._engine

    def read_pdf_page(self, data: bytes, *, page: int) -> list[SourceLine]:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(data)
        try:
            image = pdf[page - 1].render(scale=RENDER_DPI / 72).to_pil()
        finally:
            pdf.close()
        return self._read(image, page)

    def read_image(self, data: bytes, *, page: int = 1) -> list[SourceLine]:
        from PIL import Image
        return self._read(Image.open(BytesIO(data)).convert("RGB"), page)

    def _read(self, image, page: int) -> list[SourceLine]:
        import numpy as np
        with self._lock:
            results = self._load().predict(np.array(image))
        boxes: list[tuple[float, float, str, float]] = []
        for result in results:
            data = result.json.get("res", result.json) if hasattr(result, "json") else result
            for text, score, poly in zip(data.get("rec_texts", []), data.get("rec_scores", []), data.get("rec_polys", [])):
                text = " ".join(str(text).split())
                if text:
                    ys = [float(point[1]) for point in poly]
                    xs = [float(point[0]) for point in poly]
                    boxes.append((sum(ys) / len(ys), min(xs), text, float(score)))
        return [SourceLine(page, number, text[:MAX_LINE_CHARS], "ocr", int(round(score * 100)))
                for number, (_y, _x, text, score) in enumerate(_reading_order(boxes), start=1)]


def _reading_order(boxes):
    """Group boxes into rows (similar centre y), then read each row left to right."""
    rows: list[list] = []
    for box in sorted(boxes):
        if rows and abs(rows[-1][0][0] - box[0]) < 12:
            rows[-1].append(box)
        else:
            rows.append([box])
    merged = []
    for row in rows:
        row.sort(key=lambda b: b[1])
        text = " ".join(b[2] for b in row)
        merged.append((row[0][0], row[0][1], text, min(b[3] for b in row)))
    return merged


def load_default_engine():
    """PaddleOCR if the `ocr` extra is installed, else None (pages go to manual review)."""
    try:
        import paddleocr  # noqa: F401
        import pypdfium2  # noqa: F401
    except ImportError:
        return None
    return PaddleOcrEngine()
