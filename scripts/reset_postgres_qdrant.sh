#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Reset local Shkandal PostgreSQL and Qdrant state, then recreate schema and
vector collections. This does not start any ML worker.

Usage:
  scripts/reset_postgres_qdrant.sh --yes

Options:
  --yes       Required. Confirm deletion of postgres-data and qdrant-data.
  --help      Show this help.

Environment:
  DOCKER_CONTEXT       Docker context to use. Defaults to default.
  COMPOSE_PROJECT_NAME Compose project name. Defaults to repo directory name.
  POSTGRES_PORT        Local PostgreSQL port. Defaults to 5432.
  QDRANT_PORT          Local Qdrant port. Defaults to 6333.
EOF
}

confirm=false
while (($#)); do
  case "$1" in
    --yes)
      confirm=true
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if [[ "$confirm" != true ]]; then
  echo "Refusing to delete local data without --yes." >&2
  usage >&2
  exit 2
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

export DOCKER_CONTEXT="${DOCKER_CONTEXT:-default}"

load_env_file() {
  local path="$1"
  if [[ -f "$path" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$path"
    set +a
  fi
}

load_env_file ".env"
load_env_file "infra/postgres/.env"

project_name="${COMPOSE_PROJECT_NAME:-$(basename "$repo_root")}"
postgres_volume="${project_name}_postgres-data"
qdrant_volume="${project_name}_qdrant-data"

postgres_user="${POSTGRES_USER:-shkandal}"
postgres_password="${POSTGRES_PASSWORD:-shkandal_dev_password}"
postgres_db="${POSTGRES_DB:-shkandal}"
postgres_port="${POSTGRES_PORT:-5432}"
qdrant_port="${QDRANT_PORT:-6333}"

stop_worker_containers() {
  mapfile -t worker_ids < <(
    docker ps -q \
      --filter "label=com.docker.compose.project=${project_name}" \
      --filter "label=com.docker.compose.service=worker-ml"
  )
  if ((${#worker_ids[@]})); then
    echo "Stopping active worker-ml containers..."
    docker stop -t 30 "${worker_ids[@]}"
  fi
}

echo "This will delete Docker volumes:"
echo "  ${postgres_volume}"
echo "  ${qdrant_volume}"

stop_worker_containers

echo "Stopping PostgreSQL and Qdrant..."
docker compose stop postgres qdrant >/dev/null
docker compose rm -f -s -v postgres qdrant >/dev/null

echo "Removing data volumes..."
docker volume rm "$postgres_volume" "$qdrant_volume" >/dev/null 2>&1 || true

echo "Starting fresh PostgreSQL and Qdrant..."
docker compose up -d --wait postgres qdrant

echo "Running database migrations..."
POSTGRES_DATABASE_URL="postgresql+asyncpg://${postgres_user}:${postgres_password}@localhost:${postgres_port}/${postgres_db}" \
  uv run alembic -c packages/database/alembic.ini upgrade head

echo "Bootstrapping Qdrant collections..."
QDRANT_URL="http://localhost:${qdrant_port}" uv run python - <<'PY'
import asyncio

from shkandal_vector_store.bootstrap import bootstrap_qdrant_collections
from shkandal_vector_store.client import create_qdrant_client
from shkandal_vector_store.config import VectorStoreConfig


async def main() -> None:
    config = VectorStoreConfig()
    client = create_qdrant_client(config)
    try:
        await bootstrap_qdrant_collections(client, config)
    finally:
        await client.close()


asyncio.run(main())
PY

cat <<'EOF'
Reset complete.

Resolution-only worker command, when you want to start it:

DOCKER_CONTEXT=default docker compose --profile jobs run -d \
  --name shkandal-worker-ml-resolution \
  worker-ml \
  python -m worker_ml.main --loop \
  --job-type update_case_copy \
  --job-type resolve_article_cases \
  --job-type resolve_article_entities \
  --job-type resolve_article_events
EOF
