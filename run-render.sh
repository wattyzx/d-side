#!/usr/bin/env bash
set -eu

cd "$(dirname "$0")"

# Render assigns the HTTPS origin before the service starts. An explicit
# FRONTEND_URL takes precedence when a custom domain is configured later.
export FRONTEND_URL="${FRONTEND_URL:-${RENDER_EXTERNAL_URL:-}}"
if [[ "$FRONTEND_URL" != https://* ]]; then
  echo "Set FRONTEND_URL to an HTTPS origin, or run this script on Render." >&2
  exit 1
fi

# Fail before reporting healthy if a required deployment secret is absent.
# Only variable names are printed; credential values never appear in logs.
for name in TURSO_DATABASE_URL TURSO_AUTH_TOKEN DISCOGS_CONSUMER_KEY DISCOGS_CONSUMER_SECRET AUTH_ENCRYPTION_KEY; do
  if [[ -z "${!name:-}" ]]; then
    echo "Set $name in Render's environment settings before starting." >&2
    exit 1
  fi
done

exec bash run-production.sh
