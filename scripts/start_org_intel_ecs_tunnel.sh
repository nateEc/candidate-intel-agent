#!/usr/bin/env bash
set -euo pipefail

SSH_KEY="${ORG_INTEL_ECS_SSH_KEY:-$HOME/.ssh/id_org_intel_ecs}"
ECS_HOST="${ORG_INTEL_ECS_HOST:-115.190.10.83}"
ECS_USER="${ORG_INTEL_ECS_USER:-root}"
REMOTE_BIND="${ORG_INTEL_ECS_REMOTE_BIND:-127.0.0.1}"
REMOTE_PORT="${ORG_INTEL_ECS_REMOTE_PORT:-8787}"
LOCAL_BIND="${ORG_INTEL_LOCAL_BIND:-127.0.0.1}"
LOCAL_PORT="${ORG_INTEL_LOCAL_PORT:-8787}"

exec /usr/bin/ssh \
  -i "$SSH_KEY" \
  -o IdentitiesOnly=yes \
  -o BatchMode=yes \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -o TCPKeepAlive=yes \
  -N \
  -T \
  -R "${REMOTE_BIND}:${REMOTE_PORT}:${LOCAL_BIND}:${LOCAL_PORT}" \
  "${ECS_USER}@${ECS_HOST}"
