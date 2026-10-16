"""Run the standalone synthetic CareLoop evaluation baseline.

Every case receives a new SQLite database, fixed clock, and fresh demo
credentials. Result reports contain evaluation metadata and tool names only.

    uv run python evals/run_careloop.py --repeat 3
    uv run python evals/run_careloop.py --category consent --baseline evals/results/baseline.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(ROOT / "server"), str(ROOT / "alexa_sim" / "backend")]

from alexa_sim.evaluator import compare, load_cases, run  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", default=str(HERE / "careloop_cases.json"))
    parser.add_argument("--only", help="comma-separated case ids")
    parser.add_argument("--category", help="run one category")
    parser.add_argument("--baseline", help="earlier sanitized result JSON")
    parser.add_argument("--repeat", type=int, default=1, help="run every selected case N times")
    parser.add_argument("--out", help="result destination")
    args = parser.parse_args(argv)
    if args.repeat < 1:
        parser.error("--repeat must be at least one")
    cases = load_cases(args.cases)
    if args.only:
        wanted = set(args.only.split(","))
        cases = [case for case in cases if case["id"] in wanted]
    if args.category:
        cases = [case for case in cases if case["category"] == args.category]
    if not cases:
        print("No cases selected.", file=sys.stderr)
        return 2
    report = run(cases, args.repeat)
    for result in report["results"]:
        state = "PASS" if result["passed"] else "FAIL"
        tools = ", ".join(call["name"] + ("" if call["ok"] else "(denied)") for call in result["calls"]) or "no tools"
        print(f"{state}  {result['id']:<38} {tools}")
        for problem in result["problems"]:
            print(f"      - {problem}")
    summary = report["summary"]
    print(f"Passed {summary['passed']}/{summary['cases']}; always-pass {len(summary['always_pass'])}; flaky: {', '.join(summary['flaky']) or 'none'}")
    out = Path(args.out) if args.out else HERE / "results" / ("careloop-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S.json"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Results: {out}")
    if args.baseline:
        print("\n".join(compare(report, json.loads(Path(args.baseline).read_text()))))
    return 0 if summary["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
