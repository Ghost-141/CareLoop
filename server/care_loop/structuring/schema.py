"""The LLM's output contract. A proposal only: every field is checked against the source."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Kind = Literal["medication_task", "care_task", "appointment", "warning_sign", "rule_candidate", "note"]
Frequency = Literal["once_daily", "twice_daily", "three_times_daily", "four_times_daily", "every_n_hours",
                    "at_bedtime", "weekly", "as_needed", "once", "unspecified"]


class Medication(BaseModel):
    name: str | None = Field(None, description="Medicine name exactly as written")
    strength: str | None = Field(None, description="Strength exactly as written, e.g. '500 mg'")
    dose: str | None = Field(None, description="Amount per time exactly as written, e.g. '1 tablet'")
    route: str | None = Field(None, description="Route exactly as written, e.g. 'by mouth'")


class Schedule(BaseModel):
    frequency: Frequency = "unspecified"
    interval_hours: int | None = Field(None, description="Only for every_n_hours, as written")
    duration_days: int | None = Field(None, description="Only if the text states a number of days")


class RuleCandidate(BaseModel):
    measure: Literal["pain_score"] = "pain_score"
    threshold: int = Field(description="Score at or above which the clinician wants contact, as written")
    consecutive_days: int = Field(description="Number of days in a row, as written")


class ExtractedItem(BaseModel):
    kind: Kind
    label: str = Field(max_length=60, description="Short plain name for the item, no dose or medicine name")
    instruction_verbatim: str = Field(description="The instruction copied exactly from the cited lines")
    source_lines: list[str] = Field(min_length=1, description="Line ids such as p1:L12 that contain the instruction")
    medication: Medication | None = None
    schedule: Schedule | None = None
    suggested_assignee: Literal["patient", "family_member", "unspecified"] = "unspecified"
    rule: RuleCandidate | None = None
    uncertainties: list[str] = Field(default_factory=list)


class Extraction(BaseModel):
    items: list[ExtractedItem] = Field(default_factory=list)
    follow_up_date: str | None = Field(None, description="Follow-up appointment date as written, if any")
    follow_up_lines: list[str] = Field(default_factory=list)


def json_schema() -> dict:
    return Extraction.model_json_schema()
