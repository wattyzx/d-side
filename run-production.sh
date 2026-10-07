#!/usr/bin/env bash
set -eu

cd "$(dirname "$0")"

if [[ ! -x .venv/bin/python ]]; then
  echo "Install Python dependencies first; see 'Run locally' in README.md." >&2
  exit 1
fi
if [[ ! -f frontend/dist/index.html ]]; then
  echo "Build the frontend first: npm run build --prefix frontend" >&2
  exit 1
fi

export SERVE_FRONTEND=true

# Replace the shell so shutdown signals reach Uvicorn directly.
exec .venv/bin/python -m uvicorn app.api:app \
  --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}" --workers 1
