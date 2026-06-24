#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compose_file="${root_dir}/docker-compose.demo.yaml"
project_name="shkandal-e2e"

cleanup() {
  docker compose -p "${project_name}" -f "${compose_file}" down -v --remove-orphans
}
trap cleanup EXIT

cleanup
DEMO_BACKEND_PORT=18001 DEMO_FRONTEND_PORT=13001 \
  docker compose \
  -p "${project_name}" \
  -f "${compose_file}" \
  up -d --build --wait demo-backend

cd "${root_dir}/apps/frontend"
E2E_BACKEND_URL="http://localhost:18001" \
E2E_FRONTEND_URL="http://localhost:13001" \
npx playwright test "$@"
