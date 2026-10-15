"""Local LLM (Ollama) that proposes structured items. Output is constrained to the JSON schema."""
from __future__ import annotations

import json
from typing import Callable, Protocol
from urllib.request import Request, urlopen

from pydantic import ValidationError

from ..extraction.lines import SourceLine
from .prompt import SYSTEM, user_message
from .schema import Extraction, json_schema


class IntakeModel(Protocol):
    name: str

    def structure(self, lines: list[SourceLine], *, today: str, doc_type: str | None) -> Extraction: ...


class ModelUnavailable(RuntimeError):
    pass


class OllamaIntakeModel:
    def __init__(self, base_url: str, model: str, *, timeout: float = 180.0,
                 post: Callable[[str, bytes], bytes] | None = None) -> None:
        self.base_url, self.model, self.timeout = base_url.rstrip("/"), model, timeout
        self.name = f"ollama:{model}"
        self._post = post or self._http_post

    def structure(self, lines: list[SourceLine], *, today: str, doc_type: str | None) -> Extraction:
        payload = {
            "model": self.model, "stream": False, "think": False,
            "format": json_schema(),
            "options": {"temperature": 0, "num_ctx": 8192},
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": user_message(lines, today=today, doc_type=doc_type)}],
        }
        last_error: Exception | None = None
        for _attempt in range(2):  # one retry on malformed output
            try:
                raw = self._post(f"{self.base_url}/api/chat", json.dumps(payload).encode("utf-8"))
                content = json.loads(raw.decode("utf-8")).get("message", {}).get("content", "")
                return Extraction.model_validate_json(content)
            except (ValidationError, ValueError) as exc:
                last_error = exc
            except OSError as exc:
                raise ModelUnavailable("The local model is unreachable.") from exc
        raise ModelUnavailable("The local model returned invalid output twice.") from last_error

    def _http_post(self, url: str, body: bytes) -> bytes:
        request = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - configured local model URL
            return response.read()
