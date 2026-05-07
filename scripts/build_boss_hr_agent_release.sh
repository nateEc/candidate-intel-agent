#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

VERSION="${BOSS_HR_AGENT_VERSION:-$(git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)}"
DIST_DIR="${DIST_DIR:-${ROOT_DIR}/dist}"
STAGING_DIR="$(mktemp -d)"
PACKAGE_ROOT="${STAGING_DIR}/boss-hr-agent"
ARCHIVE_NAME="boss-hr-agent-macos-${VERSION}.tar.gz"
LATEST_NAME="boss-hr-agent-macos-latest.tar.gz"

cleanup() {
  rm -rf "$STAGING_DIR"
}
trap cleanup EXIT

mkdir -p "${PACKAGE_ROOT}/bin" "${PACKAGE_ROOT}/python" "${PACKAGE_ROOT}/scripts" "$DIST_DIR"

cp bin/boss-hr-agent "${PACKAGE_ROOT}/bin/"
cp requirements-hr-agent.txt "${PACKAGE_ROOT}/"
cp python/boss_hr_browser_agent.py "${PACKAGE_ROOT}/python/"
cp python/boss_job_publish_flow.py "${PACKAGE_ROOT}/python/"
cp python/boss_login_flow.py "${PACKAGE_ROOT}/python/"
cp python/boss_hr_relay_connector.py "${PACKAGE_ROOT}/python/"
cp python/boss_cdp_capture.py "${PACKAGE_ROOT}/python/"
cp python/boss_parse.py "${PACKAGE_ROOT}/python/"
cp scripts/start_boss_hr_agent.sh "${PACKAGE_ROOT}/scripts/"
cp scripts/start_boss_hr_agent_daemon.sh "${PACKAGE_ROOT}/scripts/"

cat > "${PACKAGE_ROOT}/VERSION" <<EOF
${VERSION}
EOF

chmod +x "${PACKAGE_ROOT}/bin/boss-hr-agent" \
  "${PACKAGE_ROOT}/scripts/start_boss_hr_agent.sh" \
  "${PACKAGE_ROOT}/scripts/start_boss_hr_agent_daemon.sh"

tar -C "$STAGING_DIR" -czf "${DIST_DIR}/${ARCHIVE_NAME}" boss-hr-agent
cp "${DIST_DIR}/${ARCHIVE_NAME}" "${DIST_DIR}/${LATEST_NAME}"

echo "Created ${DIST_DIR}/${ARCHIVE_NAME}"
echo "Created ${DIST_DIR}/${LATEST_NAME}"
