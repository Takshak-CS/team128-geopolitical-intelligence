#!/usr/bin/env bash
# Start all module dashboards (macOS / Linux / Git Bash).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOGS="$ROOT/.run/logs"; mkdir -p "$LOGS"

start_ui() {
    local name=$1 dir=$2 port=$3; shift 3
    local full="$ROOT/$dir"
    [ -d "$full/node_modules" ] || (cd "$full" && npm install --no-audit --no-fund >/dev/null)
    (cd "$full" && env "$@" npx vite --port "$port" --strictPort >"$LOGS/$name.log" 2>&1 &)
    echo "$name  http://localhost:$port"
}

start_ui policy_stance_ui services/policy_stance/frontend        5175 VITE_API_BASE=http://127.0.0.1:8102 VITE_API_BASE_URL=http://127.0.0.1:8102
start_ui soft_power_ui    services/soft_power/dash/frontend      5174 VITE_API_BASE_URL=http://127.0.0.1:8101
start_ui events_ui        services/event_summarization/frontend  5176 VITE_API_URL=http://127.0.0.1:8104
