"""Lazily constructed OCR engine and local model for document intake."""
from __future__ import annotations

import threading
from typing import Any

from .config import Settings


class IntakeEngines:
    def __init__(self, settings: Settings, *, ocr: Any = None, model: Any = None) -> None:
        self.settings = settings
        self._ocr, self._model = ocr, model
        self._ocr_loaded, self._model_loaded = ocr is not None, model is not None
        self._lock = threading.Lock()

    def ocr(self):
        with self._lock:
            if not self._ocr_loaded:
                self._ocr_loaded = True
                if self.settings.intake_ocr == "paddle":
                    from .extraction.ocr import load_default_engine
                    self._ocr = load_default_engine()
            return self._ocr

    def model(self):
        with self._lock:
            if not self._model_loaded:
                self._model_loaded = True
                if self.settings.intake_llm == "ollama" and self.settings.intake_model:
                    from .structuring import OllamaIntakeModel
                    self._model = OllamaIntakeModel(self.settings.llm_base_url, self.settings.intake_model)
                elif self.settings.intake_llm == "openai" and self.settings.intake_model:
                    from .structuring import OpenAIIntakeModel
                    self._model = OpenAIIntakeModel(self.settings.intake_base_url or self.settings.llm_url,
                                                    self.settings.intake_model, self.settings.llm_api_key)
            return self._model

    def describe(self) -> dict[str, str]:
        return {"ocr": self.settings.intake_ocr, "llm": self.settings.intake_llm,
                "model": self.settings.intake_model or ""}
