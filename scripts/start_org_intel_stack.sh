#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

CHROME_APP="${CHROME_APP:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
CHROME_PROFILE="${CHROME_PROFILE:-/tmp/boss-rpa-chrome}"
CHROME_DEBUG_PORT="${CHROME_DEBUG_PORT:-9222}"
ORG_INTEL_HOST="${ORG_INTEL_HOST:-127.0.0.1}"
ORG_INTEL_PORT="${ORG_INTEL_PORT:-8787}"
ORG_INTEL_DB="${ORG_INTEL_DB:-data-python/boss_talent.sqlite}"
ORG_INTEL_OUTPUT_DIR="${ORG_INTEL_OUTPUT_DIR:-org-intel}"

if [ ! -x "$CHROME_APP" ]; then
  echo "Chrome executable not found: $CHROME_APP" >&2
  exit 1
fi

if [ ! -x ".venv/bin/uvicorn" ]; then
  echo "Missing .venv/bin/uvicorn. Run: .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

if ! curl -fsS "http://127.0.0.1:${CHROME_DEBUG_PORT}/json/version" >/dev/null 2>&1; then
  echo "Starting Chrome with remote debugging on port ${CHROME_DEBUG_PORT}..."
  open -na "Google Chrome" --args \
    --remote-debugging-port="${CHROME_DEBUG_PORT}" \
    --remote-allow-origins="http://127.0.0.1:${CHROME_DEBUG_PORT}" \
    --user-data-dir="${CHROME_PROFILE}" \
    --no-first-run \
    "https://www.zhipin.com/web/chat/search"
else
  echo "Chrome remote debugging is already available on port ${CHROME_DEBUG_PORT}."
fi

echo "Starting Org Intel service on ${ORG_INTEL_HOST}:${ORG_INTEL_PORT}..."
echo "Database: ${ORG_INTEL_DB}"
echo "Output dir: ${ORG_INTEL_OUTPUT_DIR}"

export ORG_INTEL_DB
export ORG_INTEL_OUTPUT_DIR

exec .venv/bin/uvicorn python.org_intel_service:app \
  --host "${ORG_INTEL_HOST}" \
  --port "${ORG_INTEL_PORT}"
