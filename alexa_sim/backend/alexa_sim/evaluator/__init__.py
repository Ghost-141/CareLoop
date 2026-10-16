"""Scripted, deterministic evaluation baseline for the CareLoop server (no model, no network)."""

from .harness import CareEvalHarness, EvalResult, compare, load_cases, run

__all__ = ["CareEvalHarness", "EvalResult", "compare", "load_cases", "run"]
