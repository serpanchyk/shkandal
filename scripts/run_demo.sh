#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
backend_port="${DEMO_BACKEND_PORT:-18000}"
frontend_port="${DEMO_FRONTEND_PORT:-3000}"

docker compose \
  -p shkandal-demo \
  -f "${root_dir}/docker-compose.demo.yaml" \
  up -d --build --wait demo-backend

cd "${root_dir}/apps/frontend"
BACKEND_INTERNAL_URL="http://127.0.0.1:${backend_port}" \
NEXT_PUBLIC_BACKEND_URL="http://127.0.0.1:${backend_port}" \
NEXT_PUBLIC_SITE_URL="http://localhost:${frontend_port}" \
npm run dev -- --hostname 0.0.0.0 --port "${frontend_port}"
