"""LLMs that propose structured items: Ollama, or any OpenAI-compatible endpoint. Output is checked against the JSON schema."""
from __future__ import annotations

import json
import re
from typing import Callable, Protocol
from urllib.error import HTTPError
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


def chat_completions_url(base_url: str) -> str:
    """Accept a base ('https://host/v1'), a bare host, or the full '.../v1/chat/completions' URL."""
    url = base_url.strip().rstrip("/")
    if url.endswith("/chat/completions"):
        return url
    return f"{url}/chat/completions" if url.endswith("/v1") else f"{url}/v1/chat/completions"


def _json_object(text: str) -> str:
    """The JSON object in a reply, tolerating a Markdown code fence or a sentence around it."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip())
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start != -1 and end > start else text


class OpenAIIntakeModel:
    """Document structuring through any OpenAI-compatible chat completions endpoint.

    Asks for schema-constrained JSON (``response_format``). Endpoints that don't support that are
    asked in the prompt instead. Either way the reply is validated against the same schema, and
    every item still goes through the deterministic citation and number checks.
    """

    def __init__(self, base_url: str, model: str, api_key: str = "", *, timeout: float = 180.0,
                 post: Callable[[str, bytes], bytes] | None = None) -> None:
        self.url, self.model, self.api_key, self.timeout = chat_completions_url(base_url), model, api_key, timeout
        self.name = f"openai:{model}"
        self._post = post or self._http_post
        self._schema_in_prompt = False  # set once an endpoint refuses response_format

    def _payload(self, lines: list[SourceLine], today: str, doc_type: str | None) -> dict:
        user = user_message(lines, today=today, doc_type=doc_type)
        payload: dict = {"model": self.model, "temperature": 0, "messages": [{"role": "system", "content": SYSTEM},
                                                                              {"role": "user", "content": user}]}
        if self._schema_in_prompt:
            payload["messages"][1]["content"] = (user + "\n\nReply with only one JSON object that matches this JSON schema, "
                                                 "with no other text:\n" + json.dumps(json_schema()))
        else:
            payload["response_format"] = {"type": "json_schema",
                                          "json_schema": {"name": "care_plan_items", "schema": json_schema()}}
        return payload

    def structure(self, lines: list[SourceLine], *, today: str, doc_type: str | None) -> Extraction:
        last_error: Exception | None = None
        for _attempt in range(3):  # a refused response_format costs one attempt; malformed output gets a retry
            try:
                raw = self._post(self.url, json.dumps(self._payload(lines, today, doc_type)).encode("utf-8"))
                choice = (json.loads(raw.decode("utf-8")).get("choices") or [{}])[0].get("message") or {}
                content = choice.get("content") or ""
                if isinstance(content, list):  # content parts
                    content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
                return Extraction.model_validate_json(_json_object(content))
            except HTTPError as exc:
                if exc.code in (400, 422) and not self._schema_in_prompt:
                    self._schema_in_prompt = True  # the endpoint doesn't take response_format
                    last_error = exc
                    continue
                raise ModelUnavailable("The document model refused the request.") from exc
            except (ValidationError, ValueError) as exc:
                last_error = exc
            except OSError as exc:
                raise ModelUnavailable("The document model is unreachable.") from exc
        raise ModelUnavailable("The document model returned invalid output.") from last_error

    def _http_post(self, url: str, body: bytes) -> bytes:
        headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {})}
        request = Request(url, data=body, headers=headers, method="POST")
        with urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - the operator's configured model URL
            return response.read()
