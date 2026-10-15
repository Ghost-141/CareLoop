"""The scripted demo is a fail-closed, sanitized synthetic CareLoop journey."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _script_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "e2e_careloop_demo.py"
    spec = importlib.util.spec_from_file_location("careloop_e2e_demo", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_synthetic_e2e_demo_succeeds_and_report_is_sanitized(tmp_path) -> None:
    module = _script_module()
    assert module.main(["--out", str(tmp_path)]) == 0
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["passed"] is True
    assert report["summary"] == {"steps": 9, "failed": 0}
    assert report["artifacts"] == {"trace": "trace.json", "screenshots": []}
    serialized = json.dumps(report).lower()
    for forbidden in ("synthetic-patient-token", "synthetic-caregiver-token", "pain_score", "threshold", "source_id", "case_id"):
        assert forbidden not in serialized
