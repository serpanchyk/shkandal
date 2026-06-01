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
