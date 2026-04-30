#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

CHROME_APP="${CHROME_APP:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
CANDIDATES_CHROME_PROFILE="${CANDIDATES_CHROME_PROFILE:-/tmp/boss-rpa-candidates}"
CANDIDATES_CDP_PORT="${CANDIDATES_CDP_PORT:-9222}"
CANDIDATES_START_URL="${CANDIDATES_START_URL:-https://www.zhipin.com/web/chat/search}"
JOBS_CHROME_PROFILE="${JOBS_CHROME_PROFILE:-/tmp/boss-rpa-jobs}"
JOBS_CDP_PORT="${JOBS_CDP_PORT:-9223}"
JOBS_START_URL="${JOBS_START_URL:-https://www.zhipin.com/web/geek/jobs?city=100010000}"
ORG_INTEL_HOST="${ORG_INTEL_HOST:-127.0.0.1}"
ORG_INTEL_PORT="${ORG_INTEL_PORT:-8787}"
ORG_INTEL_DB="${ORG_INTEL_DB:-data-python/boss_talent.sqlite}"
ORG_INTEL_OUTPUT_DIR="${ORG_INTEL_OUTPUT_DIR:-org-intel}"
BOSS_CANDIDATES_CDP_URL="${BOSS_CANDIDATES_CDP_URL:-http://127.0.0.1:${CANDIDATES_CDP_PORT}}"
BOSS_JOBS_CDP_URL="${BOSS_JOBS_CDP_URL:-http://127.0.0.1:${JOBS_CDP_PORT}}"

if [ ! -x "$CHROME_APP" ]; then
  echo "Chrome executable not found: $CHROME_APP" >&2
  exit 1
fi

if [ ! -x ".venv/bin/uvicorn" ]; then
  echo "Missing .venv/bin/uvicorn. Run: .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

start_chrome_if_needed() {
  local label="$1"
  local port="$2"
  local profile="$3"
  local url="$4"

  if curl -fsS "http://127.0.0.1:${port}/json/version" >/dev/null 2>&1; then
    echo "${label} Chrome remote debugging is already available on port ${port}."
    return
  fi

  echo "Starting ${label} Chrome with remote debugging on port ${port}..."
  open -na "Google Chrome" --args \
    --remote-debugging-port="${port}" \
    --remote-allow-origins="http://127.0.0.1:${port}" \
    --user-data-dir="${profile}" \
    --no-first-run \
    "${url}"
}

ensure_target_url() {
  local label="$1"
  local port="$2"
  local url="$3"
  local encoded_url

  if curl -fsS "http://127.0.0.1:${port}/json/list" | grep -Fq "${url}"; then
    echo "${label} Chrome already has target: ${url}"
    return
  fi

  encoded_url="$(python3 -c 'from urllib.parse import quote; import sys; print(quote(sys.argv[1], safe=""))' "${url}")"
  echo "Opening ${label} target: ${url}"
  curl -fsS -X PUT "http://127.0.0.1:${port}/json/new?${encoded_url}" >/dev/null
}

start_chrome_if_needed "candidates/recruiter" "${CANDIDATES_CDP_PORT}" "${CANDIDATES_CHROME_PROFILE}" "${CANDIDATES_START_URL}"
start_chrome_if_needed "jobs/geek" "${JOBS_CDP_PORT}" "${JOBS_CHROME_PROFILE}" "${JOBS_START_URL}"
ensure_target_url "candidates/recruiter" "${CANDIDATES_CDP_PORT}" "${CANDIDATES_START_URL}"
ensure_target_url "jobs/geek" "${JOBS_CDP_PORT}" "${JOBS_START_URL}"

echo "Starting Org Intel service on ${ORG_INTEL_HOST}:${ORG_INTEL_PORT}..."
echo "Database: ${ORG_INTEL_DB}"
echo "Output dir: ${ORG_INTEL_OUTPUT_DIR}"
echo "Candidates CDP: ${BOSS_CANDIDATES_CDP_URL}"
echo "Jobs CDP: ${BOSS_JOBS_CDP_URL}"

export ORG_INTEL_DB
export ORG_INTEL_OUTPUT_DIR
export BOSS_CANDIDATES_CDP_URL
export BOSS_JOBS_CDP_URL
export PYTHONPATH="${ROOT_DIR}/python${PYTHONPATH:+:${PYTHONPATH}}"

exec .venv/bin/uvicorn org_intel_service:app \
  --host "${ORG_INTEL_HOST}" \
  --port "${ORG_INTEL_PORT}"
