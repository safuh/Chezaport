#!/usr/bin/env bash
set -euo pipefail

APP_PORT="${APP_PORT:-18080}"
export APP_PORT
API_URL="http://127.0.0.1:${APP_PORT}"
COMPOSE=(docker compose -f docker/compose.yml)
DASHBOARD_FILE="$(mktemp)"
cleanup() {
  "${COMPOSE[@]}" down -v --remove-orphans
  rm -f "$DASHBOARD_FILE"
}
trap cleanup EXIT

"${COMPOSE[@]}" up --build -d
echo "Waiting for API..."
for _ in {1..30}; do
  if curl --fail --silent "${API_URL}/api/health/live" >/dev/null; then
    break
  fi
  sleep 2
done

curl --fail --silent "${API_URL}/api/health/live"
curl --fail --silent "${API_URL}/api/health/ready"
curl --fail --silent --show-error --output "$DASHBOARD_FILE" "${API_URL}/"
grep --quiet "League table" "$DASHBOARD_FILE"
"${COMPOSE[@]}" exec -T api alembic upgrade head
"${COMPOSE[@]}" ps
