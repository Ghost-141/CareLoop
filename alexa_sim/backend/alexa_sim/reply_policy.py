"""The host's last privacy boundary before audio or a shared-device transcript."""
from __future__ import annotations

import re
from typing import Any

from .devices import Device


DISCLAIMER = "CareLoop is not medical advice or emergency monitoring."
UNAVAILABLE = "CareLoop couldn't complete that request."
_SDK_ERROR_PREFIX = re.compile(r"^Error executing tool [\w-]+:\s*")


def structured(result: dict[str, Any]) -> dict[str, Any]:
    data = result.get("structuredContent")
    return data if isinstance(data, dict) else {}


def error_text(result: dict[str, Any]) -> str:
    """CareLoop tool errors are generic by design; strip only the SDK prefix."""
    text = _SDK_ERROR_PREFIX.sub("", str(result.get("text") or "")).strip()
    return text if text and len(text) <= 200 else UNAVAILABLE


def speakable(result: dict[str, Any]) -> str | None:
    """Return only the server-approved ``speakable`` hint, or the generic error."""
    if result.get("isError"):
        return error_text(result)
    approved = structured(result).get("speakable")
    return approved.strip() if isinstance(approved, str) and approved.strip() else None


def compose_reply(results: list[tuple[str, dict[str, Any], bool]], *, disclaimer: bool = True) -> str:
    """Speak the outcome of the turn.

    ``results`` holds ``(tool, result, read_only)``.  When a turn performed
    actions, their outcomes are spoken (lookups that only located a ref are
    not).  Otherwise the final lookup is spoken.  Nothing outside ``speakable``
    or a generic tool error is ever narrated.
    """
    if not results:
        return ""
    errors = [r for _, r, _ in results if r.get("isError")]
    if errors:
        return speakable(errors[-1]) or UNAVAILABLE
    writes = [r for _, r, read_only in results if not read_only]
    chosen = writes or [results[-1][1]]
    lines: list[str] = []
    for result in chosen:
        line = speakable(result) or "CareLoop completed that request. Check your private screen for details."
        if line not in lines:
            lines.append(line)
    reply = " ".join(lines)
    if (disclaimer and any(structured(r).get("surface") == "private_screen" for _, r, _ in results)
            and DISCLAIMER not in reply and "not medical advice" not in reply.lower()):
        # Keep an offered question last, so it's clear what a "yes" answers.
        question = next((structured(r)["next_step"]["say"] for _, r, _ in reversed(results)
                         if (structured(r).get("next_step") or {}).get("say")), None)
        if question and reply.endswith(question):
            reply = f"{reply[:-len(question)].rstrip()} {DISCLAIMER} {question}"
        else:
            reply = f"{reply} {DISCLAIMER}"
    return reply


def screen_payload(results: list[tuple[str, dict[str, Any], bool]], device: Device) -> dict[str, Any] | None:
    """Give a personal Show the MCP App view of the turn's last successful result; never a Dot."""
    if not device.has_screen:
        return None
    for name, result, _ in reversed(results):
        data = structured(result)
        if result.get("isError") or not isinstance(data.get("view"), str):
            continue
        return {"tool": name, "resource_uri": data["view"], "result": {"structuredContent": data, "isError": False}}
    return None
