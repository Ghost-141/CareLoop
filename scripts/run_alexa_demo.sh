#!/usr/bin/env bash
# Start CareLoop (:8010) and the Alexa+ behavior simulator (:8021).
#   scripts/run_alexa_demo.sh            # uses CARELOOP_AGENT_LLM from .env
#   CARELOOP_AGENT_LLM=mock scripts/run_alexa_demo.sh   # stage-safe deterministic planner
#   VOICE=browser STT=browser scripts/run_alexa_demo.sh # browser speech instead of Kokoro/Whisper
set -euo pipefail
cd "$(dirname "$0")/.."
uv sync --inexact --extra alexa-sim --extra voice --extra intake --extra ocr >/dev/null
[ -f samples/prescription_typed.pdf ] || uv run python evals/intake/documents.py >/dev/null
uv run careloop & careloop_pid=$!
trap 'kill "$careloop_pid" 2>/dev/null || true' EXIT
port="${CARELOOP_PORT:-8010}"
for _ in $(seq 1 50); do
  curl -sf "http://127.0.0.1:${port}/healthz" >/dev/null && break
  sleep 0.2
done
curl -sf "http://127.0.0.1:${port}/healthz" >/dev/null || { echo "CareLoop did not start on :${port}" >&2; exit 1; }
echo "Open http://127.0.0.1:${CARELOOP_ALEXA_SIM_PORT:-8021}  (enable Maya and Sam in the Alexa app panel)"
uv run careloop-alexa-sim
