# CareLoop synthetic end-to-end demo

Run the verified private workflow with no server process or existing database:

```bash
scripts/run_careloop_demo.sh
# or
uv run python scripts/e2e_careloop_demo.py --out /tmp/careloop-demo
```

The script creates a temporary SQLite database and fixed synthetic patient and
caregiver credentials. It drives CareLoop's real authenticated HTTP routes,
then removes that temporary database.

The journey checks:

1. the private portal shell, an empty patient state, and denied anonymous API;
2. synthetic plan intake followed by explicit approval of two tasks and one
   source-matched rule;
3. invitation acceptance with narrow caregiver scopes;
4. three fixed-time observation writes and one deterministic alert episode;
5. a generic caregiver notification and acknowledgement;
6. a date-bounded, source-cited patient handoff; and
7. immediate denial of both a stale reload and a direct caregiver request after
   revocation.

`report.json` and `trace.json` are written to `.careloop-e2e/` by default (or
the chosen `--out` directory). They intentionally contain only step names,
pass/fail status, and check labels. They contain no tokens, IDs, source text,
observation values, alert contents, or handoff contents.

The current portal is a minimal authenticated shell, so the script uses the
actual API rather than pretend browser interaction. `--headed` and `--video`
are accepted for a future dashboard but retain the verified API mode and do not
produce a fabricated browser capture.
