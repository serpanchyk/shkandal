# Alembic Migrations

Run migrations from the repository root:

```bash
uv run alembic -c packages/database/alembic.ini upgrade head
uv run alembic -c packages/database/alembic.ini current
```
