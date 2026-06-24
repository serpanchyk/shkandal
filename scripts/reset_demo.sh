#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

docker compose \
  -p shkandal-demo \
  -f "${root_dir}/docker-compose.demo.yaml" \
  down -v --remove-orphans
docker compose \
  -p shkandal-demo \
  -f "${root_dir}/docker-compose.demo.yaml" \
  up -d --build --wait demo-backend
