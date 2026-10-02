#!/usr/bin/env bash
set -eu

cd "$(dirname "$0")"

if [[ ! -x .venv/bin/python || ! -f frontend/node_modules/vite/bin/vite.js ]]; then
  echo "Install dependencies first; see 'Run locally' in README.md." >&2
  exit 1
fi
if ! command -v node >/dev/null 2>&1; then
  echo "Node.js 22.12+ is required." >&2
  exit 1
fi

backend_pid=
frontend_pid=
cleanup() {
  trap '' INT TERM
  for pid in "$backend_pid" "$frontend_pid"; do
    if [[ -n "$pid" ]]; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

.venv/bin/python -m uvicorn app.api:app --reload &
backend_pid=$!
(cd frontend && exec node node_modules/vite/bin/vite.js) &
frontend_pid=$!

# Shut down the other server if either process exits.
while true; do
  for pid in "$backend_pid" "$frontend_pid"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      status=0
      wait "$pid" || status=$?
      exit "$status"
    fi
  done
  sleep 1
done
