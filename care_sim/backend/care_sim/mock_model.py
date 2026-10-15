"""A deliberately small deterministic planner used only for offline eval mechanics.

It accepts a closed set of demo utterances and never receives patient IDs,
credentials, source text, observations, or alert content.  Production model
selection is intentionally outside this harness.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlannedTurn:
    tool: str | None
    reply: str


class DeterministicMockModel:
    """Map known synthetic intents to a closed CareLoop tool vocabulary."""

    _INTENTS = {
        "review tasks": PlannedTurn("list_care_tasks", "I can show the approved care tasks."),
        "complete first task": PlannedTurn("record_task_completion", "I recorded the task completion."),
        "show plan source": PlannedTurn("get_care_plan_source", "I can show the linked approved source excerpt."),
        "record observation": PlannedTurn("record_observation", "I recorded the observation."),
        "search history": PlannedTurn("search_care_history", "I found matching recorded history."),
        "create handoff": PlannedTurn("create_visit_handoff", "I created a patient-generated handoff."),
        "show notifications": PlannedTurn("list_generic_notifications", "I can show generic notification status."),
        "acknowledge notification": PlannedTurn("acknowledge_alert", "I recorded the acknowledgement."),
    }

    _REFUSAL = "CareLoop does not provide clinical advice. Please use the approved plan and contact an appropriate clinician for guidance."

    def plan(self, utterance: str) -> PlannedTurn:
        normalized = utterance.strip().lower()
        if "advice" in normalized or "diagnos" in normalized or "dosage" in normalized or "dose" in normalized:
            return PlannedTurn(None, self._REFUSAL)
        try:
            return self._INTENTS[normalized]
        except KeyError:
            return PlannedTurn(None, "I can only help with the approved synthetic CareLoop workflow.")
