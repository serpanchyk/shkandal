# Run Project

## Local Environment

Docker Compose runs with tracked safe defaults. Copy the example env files when
you need local overrides:

```bash
cp .env.example .env
cp infra/postgres/.env.example infra/postgres/.env
```

## Python Checks

```bash
uv lock
uv sync --frozen --all-packages
uv run pre-commit run --all-files
uv run pytest
```

## Docker Compose

```bash
docker compose up --build
```

Default ports:

- frontend: <http://localhost:3000>
- backend: <http://localhost:8000/healthz>
- postgres: `localhost:5432`
- qdrant: <http://localhost:6333>

## Database

Start only PostgreSQL:

```bash
docker compose up -d postgres
```

PostgreSQL data is stored in the Compose `postgres-data` named volume. It
survives container restarts and `docker compose down`. To intentionally reset
local database state, remove volumes:

```bash
docker compose down -v
```

Run migrations from the repository root:

```bash
uv run alembic -c packages/database/alembic.ini upgrade head
uv run alembic -c packages/database/alembic.ini current
```

## Ingestion Worker

Run all configured media and institutional sources:

```bash
docker compose run --rm worker-ingestion
```

Run one source with a small debug limit:

```bash
docker compose run --rm worker-ingestion python -m worker_ingestion.main --source pravda --limit 20
```

Validate configured discovery endpoints and sample extraction without mutating
the database:

```bash
uv run python apps/worker-ingestion/scripts/validate_sources.py --sample 2
```

## Current Scope

The repository currently starts service shells and infrastructure, includes the
initial PostgreSQL schema/migration layer, and implements curated media and
institutional article ingestion from configured sitemaps, RSS/Atom feeds, and
section pages. It does not yet implement classifier inference, LLM resolution,
Qdrant indexing, or public dossier pages.
