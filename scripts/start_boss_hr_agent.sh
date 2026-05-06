#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

CHROME_APP="${CHROME_APP:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
HR_AGENT_HOST="${HR_AGENT_HOST:-127.0.0.1}"
HR_AGENT_PORT="${HR_AGENT_PORT:-8790}"
HR_AGENT_CDP_PORT="${HR_AGENT_CDP_PORT:-9240}"
HR_AGENT_CDP_URL="${HR_AGENT_CDP_URL:-http://127.0.0.1:${HR_AGENT_CDP_PORT}}"
HR_AGENT_CHROME_PROFILE="${HR_AGENT_CHROME_PROFILE:-/tmp/boss-hr-agent-recruiter}"
HR_AGENT_START_URL="${HR_AGENT_START_URL:-https://www.zhipin.com/web/user/?ka=header-login}"

if [ ! -x "$CHROME_APP" ]; then
  echo "Chrome executable not found: $CHROME_APP" >&2
  exit 1
fi

if [ ! -x ".venv/bin/uvicorn" ]; then
  echo "Missing .venv/bin/uvicorn. Run: .venv/bin/pip install -r requirements-hr-agent.txt" >&2
  exit 1
fi

wait_for_cdp() {
  local deadline=$((SECONDS + 15))
  while [ "$SECONDS" -lt "$deadline" ]; do
    if curl -fsS "${HR_AGENT_CDP_URL}/json/version" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.5
  done
  echo "Chrome CDP did not become available: ${HR_AGENT_CDP_URL}" >&2
  exit 1
}

if ! curl -fsS "${HR_AGENT_CDP_URL}/json/version" >/dev/null 2>&1; then
  echo "Starting recruiter Chrome with remote debugging on port ${HR_AGENT_CDP_PORT}..."
  open -na "Google Chrome" --args \
    --remote-debugging-port="${HR_AGENT_CDP_PORT}" \
    --remote-allow-origins="http://127.0.0.1:${HR_AGENT_CDP_PORT}" \
    --user-data-dir="${HR_AGENT_CHROME_PROFILE}" \
    --no-first-run \
    "${HR_AGENT_START_URL}"
  wait_for_cdp
else
  echo "Recruiter Chrome CDP is already available: ${HR_AGENT_CDP_URL}"
fi

encoded_url="$(python3 -c 'from urllib.parse import quote; import sys; print(quote(sys.argv[1], safe=""))' "${HR_AGENT_START_URL}")"
if ! curl -fsS "${HR_AGENT_CDP_URL}/json/list" | grep -Fq "zhipin.com"; then
  echo "Opening BOSS login target..."
  curl -fsS -X PUT "${HR_AGENT_CDP_URL}/json/new?${encoded_url}" >/dev/null
fi

echo "Starting BOSS HR Browser Agent on ${HR_AGENT_HOST}:${HR_AGENT_PORT}..."
echo "Chrome CDP: ${HR_AGENT_CDP_URL}"
echo "Chrome profile: ${HR_AGENT_CHROME_PROFILE}"

export HR_AGENT_HOST
export HR_AGENT_PORT
export HR_AGENT_CDP_PORT
export HR_AGENT_CDP_URL
export HR_AGENT_CHROME_PROFILE
export HR_AGENT_START_URL
export PYTHONPATH="${ROOT_DIR}/python${PYTHONPATH:+:${PYTHONPATH}}"

exec .venv/bin/uvicorn boss_hr_browser_agent:app \
  --host "${HR_AGENT_HOST}" \
  --port "${HR_AGENT_PORT}"
