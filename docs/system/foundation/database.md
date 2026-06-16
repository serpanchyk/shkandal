# Database

The `packages/database` workspace package owns shared PostgreSQL access:

- async SQLAlchemy model metadata;
- async engine and session helpers;
- Pydantic settings for `POSTGRES_DATABASE_URL`;
- Alembic migrations.

The package distribution is `shkandal-database`; the import package is
`shkandal_database`.

Runtime services should import database primitives from this package rather than
defining service-local ORM models. `infra/postgres` owns only the local
PostgreSQL container runtime.

`articles` carries durable ingestion fetch state through `fetch_status`,
`fetch_attempt_count`, `next_fetch_at`, and `last_fetch_error`. PostgreSQL is
therefore the source of truth for bounded article-fetch retries; the ingestion
worker does not rely on a URL remaining in a current feed to retry it.

## Public Reader Indexes

PostgreSQL owns public feed ordering and title search. Active Case titles have a
`pg_trgm` GIN index for typo-tolerant search. `cases.last_updated_at` represents
the newest linked article publication time; undated articles do not change it.
Sources may store a nullable frontend-owned `logo_path` using
`/sources/{source-slug}.png`; image bytes do not live in PostgreSQL.

## Session Usage

Create an async engine and session factory from settings:

```python
from shkandal_database import (
    DatabaseConfig,
    create_async_engine_from_config,
    create_async_sessionmaker,
)

engine = create_async_engine_from_config(DatabaseConfig())
session_factory = create_async_sessionmaker(engine)
```

Use `async_session_scope()` when a caller wants a transaction that commits on
success and rolls back on error.

## Migrations

Start local PostgreSQL:

```bash
docker compose up -d postgres
```

Apply migrations:

```bash
./ops/run-migrations
```

Check the current revision:

```bash
uv run alembic -c packages/database/alembic.ini current
```

Local data persists in the Compose `postgres-data` named volume. Use
`docker compose down -v` only when intentionally resetting local database state.
