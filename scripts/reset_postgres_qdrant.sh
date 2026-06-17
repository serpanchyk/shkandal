#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Reset only the derived Case/Entity/Event layer, recreate vector collections,
then enqueue Case-resolution jobs for existing Article Cards.

This preserves Sources, Articles, Article Relevance, Article Cards, and
ingestion state. It does not start any ML worker.

Usage:
  scripts/reset_postgres_qdrant.sh --yes

Options:
  --yes       Required. Confirm deletion of derived Case/Entity/Event state.
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

database_url="postgresql+asyncpg://${postgres_user}:${postgres_password}@localhost:${postgres_port}/${postgres_db}"

echo "This will delete derived data only:"
echo "  cases, events, entities, their links/audits, related jobs, and related LLM runs"
echo "It will preserve articles, article_relevance, article_cards, sources, and ingestion state."

stop_worker_containers

echo "Starting PostgreSQL and Qdrant..."
docker compose up -d --wait postgres qdrant

echo "Running database migrations..."
POSTGRES_DATABASE_URL="${database_url}" uv run alembic -c packages/database/alembic.ini upgrade head

echo "Clearing derived Case/Entity/Event data..."
POSTGRES_DATABASE_URL="${database_url}" uv run python - <<'PY'
import asyncio

from shkandal_database.config import DatabaseConfig
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DERIVED_JOB_TYPES = (
    "resolve_article_cases",
    "resolve_article_entities",
    "resolve_article_events",
    "update_case_copy",
    "audit_case_coherence",
    "audit_case_public_interest",
    "audit_case_duplicates",
)

DERIVED_LLM_RUN_TYPES = (
    "case_resolution",
    "entity_resolution",
    "event_resolution",
    "case_copy_update",
    "case_link_audit",
    "case_coherence_audit",
    "case_public_interest_audit",
    "case_duplicate_audit",
)


async def main() -> None:
    engine = create_async_engine(DatabaseConfig().async_database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM jobs WHERE job_type = ANY(:job_types)"),
                {"job_types": list(DERIVED_JOB_TYPES)},
            )
            await connection.execute(text("DELETE FROM llm_cooldowns"))
            await connection.execute(
                text(
                    """
                    TRUNCATE TABLE
                        case_duplicate_audits,
                        case_public_interest_audits,
                        case_coherence_audits,
                        case_events,
                        case_entities,
                        article_event_cases,
                        article_entity_cases,
                        article_events,
                        article_entities,
                        case_relations,
                        case_articles,
                        events,
                        entities
                    RESTART IDENTITY CASCADE
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    UPDATE cases
                    SET merged_into_case_id = NULL
                    WHERE merged_into_case_id IS NOT NULL
                    """
                )
            )
            await connection.execute(text("TRUNCATE TABLE cases RESTART IDENTITY CASCADE"))
            await connection.execute(
                text("DELETE FROM llm_runs WHERE run_type = ANY(:run_types)"),
                {"run_types": list(DERIVED_LLM_RUN_TYPES)},
            )
    finally:
        await engine.dispose()


asyncio.run(main())
PY

echo "Recreating Qdrant collections..."
QDRANT_URL="http://localhost:${qdrant_port}" uv run python - <<'PY'
import asyncio

from shkandal_vector_store.bootstrap import bootstrap_qdrant_collections
from shkandal_vector_store.client import create_qdrant_client
from shkandal_vector_store.config import VectorStoreConfig


async def main() -> None:
    config = VectorStoreConfig()
    client = create_qdrant_client(config)
    try:
        for collection_name in (
            config.case_collection_name,
            config.entity_collection_name,
            config.event_collection_name,
        ):
            if await client.collection_exists(collection_name):
                await client.delete_collection(collection_name)
        await bootstrap_qdrant_collections(client, config)
    finally:
        await client.close()


asyncio.run(main())
PY

echo "Enqueueing Case-resolution jobs for case-candidate Article Cards..."
POSTGRES_DATABASE_URL="${database_url}" uv run python -m worker_ml.enqueue_case_resolution_jobs --apply

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
