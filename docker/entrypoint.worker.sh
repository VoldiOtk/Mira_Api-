#!/bin/bash
set -e

echo "[entrypoint] Waiting for PostgreSQL..."
MAX_WAIT=60
WAITED=0
until pg_isready -h "${PGHOST:-postgres}" -p "${PGPORT:-5432}" -U "${PGUSER:-mira}" 2>/dev/null; do
  if [ "$WAITED" -ge "$MAX_WAIT" ]; then
    echo "[entrypoint] ERROR: PostgreSQL did not become ready within ${MAX_WAIT}s. Aborting."
    exit 1
  fi
  echo "[entrypoint] PostgreSQL not ready yet, retrying in 2s... (${WAITED}s elapsed)"
  sleep 2
  WAITED=$((WAITED + 2))
done
echo "[entrypoint] PostgreSQL ready."

echo "[entrypoint] Waiting for Redis..."
MAX_WAIT=30
WAITED=0
until redis-cli -h "${REDIS_HOST:-redis}" ping 2>/dev/null | grep -q PONG; do
  if [ "$WAITED" -ge "$MAX_WAIT" ]; then
    echo "[entrypoint] ERROR: Redis did not become ready within ${MAX_WAIT}s. Aborting."
    exit 1
  fi
  echo "[entrypoint] Redis not ready yet, retrying in 2s... (${WAITED}s elapsed)"
  sleep 2
  WAITED=$((WAITED + 2))
done
echo "[entrypoint] Redis ready."

echo "[entrypoint] Starting Celery worker..."
exec celery -A backend.workers.celery_app.celery_app worker --loglevel=info --concurrency=2 -Q celery
