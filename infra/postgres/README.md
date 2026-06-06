# Postgres

PostgreSQL is Shkandal's source of truth. Qdrant is rebuildable from this data.

For local Compose runs, copy `infra/postgres/.env.example` to
`infra/postgres/.env`.

This env file owns only PostgreSQL bootstrap credentials. Keep them consistent
with the credentials embedded in root `POSTGRES_DATABASE_URL`.

The root `docker-compose.yaml` starts PostgreSQL with:

- image `postgres:16-alpine`;
- bootstrap credentials from ignored `infra/postgres/.env`;
- named volume `postgres-data:/var/lib/postgresql/data`;
- init scripts from `infra/postgres/init`.

Start local PostgreSQL:

```bash
docker compose up -d postgres
```

The named volume persists data across container restarts and `docker compose
down`. To intentionally reset local database state, remove volumes:

```bash
docker compose down -v
```

Run schema migrations from the repository root:

```bash
uv run alembic -c packages/database/alembic.ini upgrade head
```
