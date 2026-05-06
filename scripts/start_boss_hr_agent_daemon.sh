#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

HR_AGENT_HOST="${HR_AGENT_HOST:-127.0.0.1}"
HR_AGENT_PORT="${HR_AGENT_PORT:-8790}"
HR_AGENT_LOG="${HR_AGENT_LOG:-/tmp/boss-hr-agent-service.log}"
HR_AGENT_PID_FILE="${HR_AGENT_PID_FILE:-/tmp/boss-hr-agent-service.pid}"

health_url="http://${HR_AGENT_HOST}:${HR_AGENT_PORT}/health"

if curl -fsS "$health_url" >/dev/null 2>&1; then
  echo "BOSS HR Browser Agent already running: ${health_url}"
  exit 0
fi

if [ ! -x "./scripts/start_boss_hr_agent.sh" ]; then
  echo "Missing executable script: ./scripts/start_boss_hr_agent.sh" >&2
  exit 1
fi

if [ ! -x ".venv/bin/uvicorn" ]; then
  echo "Missing .venv/bin/uvicorn. Run setup first:" >&2
  echo "  python3 -m venv .venv" >&2
  echo "  .venv/bin/pip install -r requirements-hr-agent.txt" >&2
  exit 1
fi

if [ -f "$HR_AGENT_PID_FILE" ]; then
  existing_pid="$(cat "$HR_AGENT_PID_FILE" 2>/dev/null || true)"
  if [ -n "$existing_pid" ] && kill -0 "$existing_pid" 2>/dev/null; then
    echo "Found existing HR agent process ${existing_pid}; waiting for health..."
  else
    rm -f "$HR_AGENT_PID_FILE"
  fi
fi

mkdir -p "$(dirname "$HR_AGENT_LOG")"

if [ ! -f "$HR_AGENT_PID_FILE" ]; then
  echo "Starting BOSS HR Browser Agent in background..."
  nohup ./scripts/start_boss_hr_agent.sh >"$HR_AGENT_LOG" 2>&1 &
  echo "$!" > "$HR_AGENT_PID_FILE"
fi

deadline=$((SECONDS + 30))
while [ "$SECONDS" -lt "$deadline" ]; do
  if curl -fsS "$health_url" >/dev/null 2>&1; then
    echo "BOSS HR Browser Agent ready: ${health_url}"
    echo "Log: ${HR_AGENT_LOG}"
    echo "PID file: ${HR_AGENT_PID_FILE}"
    exit 0
  fi

  pid="$(cat "$HR_AGENT_PID_FILE" 2>/dev/null || true)"
  if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then
    echo "BOSS HR Browser Agent exited before becoming ready." >&2
    echo "Log: ${HR_AGENT_LOG}" >&2
    tail -n 40 "$HR_AGENT_LOG" >&2 || true
    rm -f "$HR_AGENT_PID_FILE"
    exit 1
  fi

  sleep 0.5
done

echo "Timed out waiting for BOSS HR Browser Agent: ${health_url}" >&2
echo "Log: ${HR_AGENT_LOG}" >&2
tail -n 40 "$HR_AGENT_LOG" >&2 || true
exit 1
