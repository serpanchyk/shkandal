# Alembic Migrations

Run migrations from the repository root:

```bash
./ops/run-migrations
uv run alembic -c packages/database/alembic.ini current
```
