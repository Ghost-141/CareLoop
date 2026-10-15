#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
# Terminal 1: uv run careloop
# This process serves the local browser simulator. Ollama is required for
# natural-language responses; the browser keeps typed input as a stage fallback.
PYTHONPATH=server:care_sim/backend uv run careloop-voice-sim
