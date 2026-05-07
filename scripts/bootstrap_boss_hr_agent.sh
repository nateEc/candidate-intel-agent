#!/usr/bin/env bash
set -euo pipefail

DEFAULT_HOME="${HOME}/Library/Application Support/BossHrAgent"
BOSS_HR_AGENT_HOME="${BOSS_HR_AGENT_HOME:-${DEFAULT_HOME}}"
INSTALL_DIR="${BOSS_HR_AGENT_INSTALL_DIR:-${BOSS_HR_AGENT_HOME}/service}"
DEFAULT_RELEASE_URL="https://github.com/nateEc/candidate-intel-agent/releases/latest/download/boss-hr-agent-macos-latest.tar.gz"
DEFAULT_SOURCE_URL="https://github.com/nateEc/candidate-intel-agent/archive/refs/heads/main.tar.gz"
DOWNLOAD_URL="${BOSS_HR_AGENT_ARCHIVE_URL:-${DEFAULT_RELEASE_URL}}"
FALLBACK_URL="${BOSS_HR_AGENT_FALLBACK_ARCHIVE_URL:-${DEFAULT_SOURCE_URL}}"
LOCAL_ARCHIVE="${BOSS_HR_AGENT_LOCAL_ARCHIVE:-}"
SKIP_DOWNLOAD="${BOSS_HR_AGENT_SKIP_DOWNLOAD:-0}"
NO_START="${BOSS_HR_AGENT_NO_START:-0}"
HR_AGENT_HOST="${HR_AGENT_HOST:-127.0.0.1}"
HR_AGENT_PORT="${HR_AGENT_PORT:-8790}"

export BOSS_HR_AGENT_HOME
export HR_AGENT_HOST
export HR_AGENT_PORT

mkdir -p "$BOSS_HR_AGENT_HOME"

if [ "$SKIP_DOWNLOAD" = "1" ] && [ -x "${INSTALL_DIR}/bin/boss-hr-agent" ]; then
  "${INSTALL_DIR}/bin/boss-hr-agent" start
  exit 0
fi

tmp_dir="$(mktemp -d)"
cleanup() {
  rm -rf "$tmp_dir"
}
trap cleanup EXIT

archive_path="${tmp_dir}/boss-hr-agent.tar.gz"

if [ -n "$LOCAL_ARCHIVE" ]; then
  cp "$LOCAL_ARCHIVE" "$archive_path"
else
  echo "Downloading BOSS HR Browser Agent..."
  if ! curl -fL "$DOWNLOAD_URL" -o "$archive_path"; then
    if [ "$DOWNLOAD_URL" = "$FALLBACK_URL" ]; then
      echo "Download failed: ${DOWNLOAD_URL}" >&2
      exit 1
    fi
    echo "Release artifact unavailable, falling back to source archive..."
    curl -fL "$FALLBACK_URL" -o "$archive_path"
  fi
fi

mkdir -p "${tmp_dir}/extract"
tar -xzf "$archive_path" -C "${tmp_dir}/extract"

find_source_root() {
  local root
  root="$(find "${tmp_dir}/extract" -type f -path "*/python/boss_hr_browser_agent.py" -print -quit)"
  if [ -z "$root" ]; then
    return 1
  fi
  dirname "$(dirname "$root")"
}

SOURCE_ROOT="$(find_source_root)"
if [ -z "$SOURCE_ROOT" ]; then
  echo "Downloaded archive does not contain BOSS HR Browser Agent service files." >&2
  exit 1
fi

staging="${tmp_dir}/service"
mkdir -p "${staging}/bin" "${staging}/python" "${staging}/scripts"

copy_required() {
  local source="$1"
  local destination="$2"
  if [ ! -f "$source" ]; then
    echo "Missing required file in archive: ${source}" >&2
    exit 1
  fi
  cp "$source" "$destination"
}

copy_required "${SOURCE_ROOT}/bin/boss-hr-agent" "${staging}/bin/"
if [ -f "${SOURCE_ROOT}/requirements-hr-agent.txt" ]; then
  cp "${SOURCE_ROOT}/requirements-hr-agent.txt" "${staging}/"
else
  copy_required "${SOURCE_ROOT}/requirements.txt" "${staging}/requirements-hr-agent.txt"
fi
copy_required "${SOURCE_ROOT}/python/boss_hr_browser_agent.py" "${staging}/python/"
copy_required "${SOURCE_ROOT}/python/boss_job_publish_flow.py" "${staging}/python/"
copy_required "${SOURCE_ROOT}/python/boss_login_flow.py" "${staging}/python/"
copy_required "${SOURCE_ROOT}/python/boss_hr_relay_connector.py" "${staging}/python/"
copy_required "${SOURCE_ROOT}/python/boss_cdp_capture.py" "${staging}/python/"
copy_required "${SOURCE_ROOT}/python/boss_parse.py" "${staging}/python/"
copy_required "${SOURCE_ROOT}/scripts/start_boss_hr_agent.sh" "${staging}/scripts/"
copy_required "${SOURCE_ROOT}/scripts/start_boss_hr_agent_daemon.sh" "${staging}/scripts/"

if [ -f "${SOURCE_ROOT}/VERSION" ]; then
  cp "${SOURCE_ROOT}/VERSION" "${staging}/"
fi

chmod +x "${staging}/bin/boss-hr-agent" \
  "${staging}/scripts/start_boss_hr_agent.sh" \
  "${staging}/scripts/start_boss_hr_agent_daemon.sh"

if [ -x "${INSTALL_DIR}/bin/boss-hr-agent" ]; then
  "${INSTALL_DIR}/bin/boss-hr-agent" stop >/dev/null 2>&1 || true
fi

rm -rf "${INSTALL_DIR}.previous"
if [ -d "$INSTALL_DIR" ]; then
  mv "$INSTALL_DIR" "${INSTALL_DIR}.previous"
fi
mkdir -p "$(dirname "$INSTALL_DIR")"
mv "$staging" "$INSTALL_DIR"

if [ "$NO_START" != "1" ]; then
  "${INSTALL_DIR}/bin/boss-hr-agent" start
fi

cat <<EOF
BOSS HR Browser Agent installed$([ "$NO_START" = "1" ] && printf "." || printf " and started.")
Service dir: ${INSTALL_DIR}
Home: ${BOSS_HR_AGENT_HOME}
Health: http://${HR_AGENT_HOST}:${HR_AGENT_PORT}/health
EOF
