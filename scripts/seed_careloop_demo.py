#!/usr/bin/env python3
"""Seed the synthetic starting state for the Alexa+ demo (see care_loop/demo.py).

Maya has accepted data use, Sam is in her care circle, and three days of pain
check-ins are logged (yesterday's was 7). Her prescription is not loaded yet.

    uv run python scripts/seed_careloop_demo.py            # only into an empty demo patient
    uv run python scripts/seed_careloop_demo.py --reset    # wipe the demo patient, then seed
    uv run python scripts/seed_careloop_demo.py --empty    # wipe the demo patient, seed nothing
    uv run python scripts/seed_careloop_demo.py --db /tmp/careloop-video.db --reset
    uv run python scripts/seed_careloop_demo.py --reset --story history   # day four at home

--story history seeds an approved, cited plan with three days of history instead (see care_loop/demo.py).
It can also be set with CARELOOP_DEMO_STORY=history, which Reset demo data in the simulator follows too.

--reset and --empty delete only the configured demo patient's records, never other patients.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "server") not in sys.path:
    sys.path.insert(0, str(ROOT / "server"))

from care_loop.config import Settings
from care_loop.demo import STORIES, demo_story, has_records, is_seeded, reset_demo, seed_demo, seed_history
from care_loop.server import build_deps


def main(argv: list[str] | None = None) -> int:
    settings = Settings.from_env()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, default=Path(settings.db_path), help="SQLite database to seed")
    parser.add_argument("--reset", action="store_true", help="delete the demo patient's records first")
    parser.add_argument("--empty", action="store_true", help="delete the demo patient's records and seed nothing")
    parser.add_argument("--story", choices=STORIES, default=demo_story(),
                        help="first-visit (default): the prescription is not loaded yet; history: day four at home")
    args = parser.parse_args(argv)

    from dataclasses import replace
    deps = build_deps(replace(settings, db_path=str(args.db)))
    service, patient = deps.service, settings.patient_id
    try:
        if args.empty:
            deps.storage.wipe_patient(patient)
            print("The demo patient is empty: no consent, no care circle, no records.")
            return 0
        if not args.reset and has_records(service, patient):
            state = "the demo data" if is_seeded(service, patient) else "records"
            print(f"The demo patient already has {state}; nothing changed. Use --reset to start over.")
            return 0
        if args.reset:
            summary = reset_demo(service, patient, settings.caregiver_id, args.story)
        else:
            summary = (seed_history if args.story == "history" else seed_demo)(service, patient, settings.caregiver_id)
    finally:
        deps.storage.close()
    print(f"Seeded synthetic demo data in {args.db}:")
    print(f"  {summary['patient_name']} has accepted data use; care circle: {', '.join(summary['care_circle'])}")
    if summary.get("story") == "history":
        print("  day four at home: the prescription is approved and cited, Sam does the 9 PM dressing change")
        print(f"  pain check-ins, oldest first, today's last: {summary['pain_history']}")
        print(f"  yesterday's dressing change was missed ({summary['missed_tasks']}); last teach-back: {summary['teach_back']}")
        print(f"  1 question saved for the clinician; follow-up visit on {summary['follow_up']}")
        return 0
    print(f"  pain check-ins for the last {len(summary['pain_history'])} days: {summary['pain_history']}")
    print("  1 question saved for the clinician; prescription not loaded (share it in the demo)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
