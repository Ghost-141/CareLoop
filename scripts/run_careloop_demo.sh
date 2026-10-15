#!/usr/bin/env sh
# Run only the self-contained synthetic CareLoop journey.
set -eu
exec uv run python scripts/e2e_careloop_demo.py "$@"
