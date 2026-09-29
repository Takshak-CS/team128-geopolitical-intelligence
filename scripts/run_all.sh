#!/usr/bin/env bash
# Start all five services (macOS / Linux / Git Bash). Stop with: scripts/run_all.sh stop
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python"; [ -x "$PY" ] || PY="$ROOT/.venv/Scripts/python.exe"
LOGS="$ROOT/.run/logs"; mkdir -p "$LOGS"

if [ "${1:-}" = "stop" ]; then
  for pidfile in "$ROOT"/.run/*.pid; do [ -f "$pidfile" ] && kill "$(cat "$pidfile")" 2>/dev/null && rm -f "$pidfile"; done
  echo "stopped"; exit 0
fi

start() { # name port dir app [ENV=VAL ...]
  local name=$1 port=$2 dir=$3 app=$4; shift 4
  (cd "$ROOT/$dir" && env "$@" "$PY" -m uvicorn "$app" --host 127.0.0.1 --port "$port" >"$LOGS/$name.log" 2>&1 & echo $! >"$ROOT/.run/$name.pid")
  echo "$name starting on :$port"
}

echo "Checking Policy Stance datasets..."
bash "$ROOT/scripts/download_policy_data.sh"

start soft_power 8101 services/soft_power/dash/backend app.main:app DATA_SOURCE=files
start policy_stance 8102 services/policy_stance backend.main:app
start trade_intelligence 8103 services/trade_intelligence api.app:app TRADE_CACHE_DIR="$ROOT/services/trade_intelligence/cache"
start event_summarization 8104 services/event_summarization src.api:app
start orchestrator 8000 orchestrator app.main:app

echo "Waiting for the orchestrator..."
for _ in $(seq 1 60); do curl -sf http://127.0.0.1:8000/health >/dev/null && break; sleep 2; done
curl -s http://127.0.0.1:8000/health; echo
echo "Starting module dashboards..."
bash "$ROOT/scripts/run_dashboards.sh" 2>/dev/null || true

echo "Briefing UI: http://127.0.0.1:8000"
