"""Closed-vocabulary synthetic agent facade used by CareLoop evals."""
from __future__ import annotations

from .mock_model import DeterministicMockModel


class CareSimAgent:
    def __init__(self, model: DeterministicMockModel | None = None) -> None:
        self.model = model or DeterministicMockModel()

    def turn(self, utterance: str):
        return self.model.plan(utterance)
