#!/usr/bin/env bash
set -eu

cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3.10+ is required to build the backend environment." >&2
  exit 1
fi
if ! command -v npm >/dev/null 2>&1; then
  echo "Node.js 22.12+ and npm are required to build the frontend." >&2
  exit 1
fi

if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install -r requirements.txt

# Vite and TypeScript are build dependencies, including on production hosts.
npm ci --prefix frontend --include=dev
npm run build --prefix frontend
