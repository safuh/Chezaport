#!/usr/bin/env bash
set -euo pipefail

COMPOSE=(docker compose -f docker/compose.staging.yml)
: "${DATABASE_URL:?DATABASE_URL must be set to a staging PostgreSQL database}"

"${COMPOSE[@]}" config --quiet
"${COMPOSE[@]}" build
"${COMPOSE[@]}" run --rm api alembic upgrade head
"${COMPOSE[@]}" up -d

echo "Waiting for staging readiness..."
for _ in {1..30}; do
  if curl --fail --silent "http://127.0.0.1:${APP_PORT:-8001}/api/health/ready" >/dev/null; then
    echo "Staging deployment is ready."
    exit 0
  fi
  sleep 2
done

echo "Staging API did not become ready in time." >&2
"${COMPOSE[@]}" ps
exit 1
