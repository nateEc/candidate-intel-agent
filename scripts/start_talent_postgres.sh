#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

CONTAINER_NAME="${TALENT_POSTGRES_CONTAINER:-boss-talent-postgres}"
IMAGE="${TALENT_POSTGRES_IMAGE:-pgvector/pgvector:pg16}"
HOST="${TALENT_POSTGRES_HOST:-127.0.0.1}"
PORT="${TALENT_POSTGRES_PORT:-54329}"
USER="${TALENT_POSTGRES_USER:-talent}"
PASSWORD="${TALENT_POSTGRES_PASSWORD:-talent_dev_password}"
DB="${TALENT_POSTGRES_DB:-talent_library}"
VOLUME="${TALENT_POSTGRES_VOLUME:-boss-talent-postgres-data}"
DATABASE_URL="postgresql://${USER}:${PASSWORD}@${HOST}:${PORT}/${DB}"

if ! docker info >/dev/null 2>&1; then
  open -a Docker >/dev/null 2>&1 || true
  deadline=$((SECONDS + 90))
  while [ "$SECONDS" -lt "$deadline" ]; do
    docker info >/dev/null 2>&1 && break
    sleep 2
  done
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon is not running. Please start Docker Desktop and retry." >&2
  exit 1
fi

if docker ps -a --format '{{.Names}}' | grep -Fxq "$CONTAINER_NAME"; then
  if ! docker ps --format '{{.Names}}' | grep -Fxq "$CONTAINER_NAME"; then
    docker start "$CONTAINER_NAME" >/dev/null
  fi
else
  docker run -d \
    --name "$CONTAINER_NAME" \
    -e POSTGRES_USER="$USER" \
    -e POSTGRES_PASSWORD="$PASSWORD" \
    -e POSTGRES_DB="$DB" \
    -p "${HOST}:${PORT}:5432" \
    -v "${VOLUME}:/var/lib/postgresql/data" \
    "$IMAGE" >/dev/null
fi

deadline=$((SECONDS + 60))
while [ "$SECONDS" -lt "$deadline" ]; do
  if PGPASSWORD="$PASSWORD" psql -h "$HOST" -p "$PORT" -U "$USER" -d "$DB" -c "select 1" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! PGPASSWORD="$PASSWORD" psql -h "$HOST" -p "$PORT" -U "$USER" -d "$DB" -c "select 1" >/dev/null 2>&1; then
  echo "Postgres did not become ready on ${HOST}:${PORT}." >&2
  docker logs --tail 80 "$CONTAINER_NAME" >&2 || true
  exit 1
fi

if [ ! -f ".env" ] || ! grep -q '^DATABASE_URL=' ".env"; then
  printf 'DATABASE_URL=%s\n' "$DATABASE_URL" >> ".env"
fi

echo "Postgres ready: ${CONTAINER_NAME}"
echo "DATABASE_URL=${DATABASE_URL}"
