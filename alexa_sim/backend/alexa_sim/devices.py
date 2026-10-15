from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class DeviceKind(StrEnum):
    SHOW = "show"
    DOT = "dot"


class DeviceState(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"


@dataclass
class PendingAction:
    """A destructive tool call waiting for the person's spoken confirmation."""
    name: str
    arguments: dict[str, Any]
    prompt: str


@dataclass
class Device:
    id: str
    kind: DeviceKind
    owner: str  # the account this device belongs to once linked ("maya" / "sam")
    account: str | None = None
    state: DeviceState = DeviceState.IDLE
    history: list[dict[str, str]] = field(default_factory=list)
    pending: PendingAction | None = None
    notification: bool = False
    awaiting: Any = None  # orchestrator.Awaiting: a tool call paused on an MCP elicitation
    offer: dict[str, Any] | None = None  # a next step the server offered; "yes" runs it (one turn only)
    context: dict[str, Any] = field(default_factory=dict)  # last task / person mentioned, for "it" and "him"
    disclaimed: bool = False  # the care disclaimer is spoken once per linked session

    @property
    def has_screen(self) -> bool:
        return self.kind == DeviceKind.SHOW

    def remember(self, user: str, assistant: str, tool_messages: list[dict[str, Any]] | None = None) -> None:
        """Record one turn: the request, any tool calls with voice-safe results, the reply.

        Keeping the tool calls in history teaches the planner model *how* earlier turns
        were done (e.g. a check-in is a tool call), not just what was said.
        """
        self.history.extend([{"role": "user", "content": user}, *(tool_messages or []),
                             {"role": "assistant", "content": assistant}])
        starts = [i for i, message in enumerate(self.history) if message["role"] == "user"]
        if len(starts) > 6:  # trim on turn boundaries so tool calls keep their results
            del self.history[:starts[-6]]

    def event(self, type: str, **payload: object) -> dict[str, object]:
        return {"type": type, "device_id": self.id, "state": self.state, "notification": self.notification, **payload}
