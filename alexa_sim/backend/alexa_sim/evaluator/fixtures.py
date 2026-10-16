"""Fixed synthetic identities and time for isolated CareLoop evaluations."""
from __future__ import annotations

from dataclasses import dataclass

from care_loop.auth import Identity


@dataclass
class FixedClock:
    """A clock controlled only by the evaluator, never by a model turn."""

    value: int = 1_735_689_600  # 2025-01-01T00:00:00Z, synthetic demo time

    def __call__(self) -> int:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += seconds


def personas() -> dict[str, Identity]:
    """Return fresh credential-derived demo identities for one isolated case."""

    return {
        "patient": Identity("patient-demo", "patient", "patient-demo"),
        "other_patient": Identity("other-patient-demo", "patient", "other-patient-demo"),
        "caregiver": Identity("caregiver-demo", "caregiver", "patient-demo"),
        "other_caregiver": Identity("other-caregiver-demo", "caregiver", "patient-demo"),
        "outsider": Identity("outsider-demo", "caregiver", "other-patient-demo"),
    }
