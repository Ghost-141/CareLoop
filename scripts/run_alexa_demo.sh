#!/usr/bin/env bash
# Start CareLoop (default :8010) and the Alexa+ behavior simulator (default :8021).
#   scripts/run_alexa_demo.sh            # uses CARELOOP_AGENT_LLM from .env
#   CARELOOP_AGENT_LLM=mock scripts/run_alexa_demo.sh   # stage-safe deterministic planner
#   VOICE=browser STT=browser scripts/run_alexa_demo.sh # browser speech instead of Kokoro/Whisper
#   scripts/run_alexa_demo.sh --reset    # wipe the demo patient and start from the seeded starting day
#   scripts/run_alexa_demo.sh --empty    # wipe the demo patient and start with nothing (docs/CARELOOP_DEMO_WALKTHROUGH.md)
# The demo patient is seeded with synthetic starting data when it has no records yet.
# If a port is taken (by another app or an old run), the next free port is used and printed.
set -euo pipefail
cd "$(dirname "$0")/.."
seed_args=()
for arg in "$@"; do
  case "$arg" in
    --reset|--empty) seed_args+=("$arg") ;;
    *) echo "Unknown option: $arg (use --reset or --empty)" >&2; exit 2 ;;
  esac
done

free_port() {  # first port from $1 upward that can be bound on 127.0.0.1
  python3 - "$1" <<'PY'
import socket, sys
start = int(sys.argv[1])
for port in range(start, start + 30):
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            continue
        print(port)
        sys.exit(0)
sys.exit(1)
PY
}

want_server="${CARELOOP_PORT:-8010}"
want_sim="${CARELOOP_ALEXA_SIM_PORT:-8021}"
server_port="$(free_port "$want_server")" || { echo "No free port near ${want_server}" >&2; exit 1; }
sim_port="$(free_port "$want_sim")" || { echo "No free port near ${want_sim}" >&2; exit 1; }
[ "$server_port" = "$sim_port" ] && sim_port="$(free_port "$((sim_port + 1))")"
[ "$server_port" != "$want_server" ] && echo "Port ${want_server} is busy; CareLoop will use ${server_port}."
[ "$sim_port" != "$want_sim" ] && echo "Port ${want_sim} is busy; the simulator will use ${sim_port}."
# Shell variables take precedence over .env, so both processes agree on these.
export CARELOOP_PORT="$server_port" CARELOOP_ALEXA_SIM_PORT="$sim_port"
export CARELOOP_MCP_URL="http://127.0.0.1:${server_port}/mcp"
# The simulator's "Reset demo data" button (and idle reset, if set) needs this.
export CARELOOP_DEMO_RESET="${CARELOOP_DEMO_RESET:-true}"

uv sync --inexact --extra alexa-sim --extra voice --extra intake --extra ocr >/dev/null
[ -f samples/prescription_typed.pdf ] || uv run python evals/intake/documents.py >/dev/null
uv run python scripts/seed_careloop_demo.py ${seed_args[@]+"${seed_args[@]}"}
uv run careloop & careloop_pid=$!
trap 'kill "$careloop_pid" 2>/dev/null || true' EXIT
for _ in $(seq 1 50); do
  curl -sf "http://127.0.0.1:${server_port}/healthz" >/dev/null && break
  kill -0 "$careloop_pid" 2>/dev/null || { echo "CareLoop exited during startup" >&2; exit 1; }
  sleep 0.2
done
curl -sf "http://127.0.0.1:${server_port}/healthz" >/dev/null || { echo "CareLoop did not start on :${server_port}" >&2; exit 1; }
echo "Open http://127.0.0.1:${sim_port}  (enable Maya and Sam in the Alexa app panel, or press Reset demo data)"
uv run careloop-alexa-sim
