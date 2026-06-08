# Run Project

This is the local runbook for starting Shkandal, checking that services are
healthy, watching logs, and handling common development operations.

## Local Environment

Create the three ignored runtime env files from their tracked examples before
running Docker Compose:

```bash
cp .env.example .env
cp infra/postgres/.env.example infra/postgres/.env
cp infra/litellm/.env.example infra/litellm/.env
```

The root `.env` contains shared application and Compose configuration, including
the application database URL, LiteLLM proxy access, and optional LangSmith
tracing settings. `infra/postgres/.env` contains PostgreSQL bootstrap
credentials. `infra/litellm/.env` contains external provider API keys.

Keep `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB` in the PostgreSQL
env consistent with the credentials embedded in root `POSTGRES_DATABASE_URL`.
Generate a unique root `LLM_API_KEY`; Compose also supplies it to LiteLLM as
`LITELLM_MASTER_KEY`.

## Python Checks

```bash
uv lock
uv sync --frozen --all-packages
uv run pre-commit run --all-files
uv run pytest
```

Validate Compose configuration:

```bash
docker compose config
```

## Model Artifacts

DVC tracks large model binaries under `artifacts/models/`. Git tracks the small
`manifest.json` files and `.dvc` pointer files beside the binaries.

Check local artifact state:

```bash
uv run dvc status
```

After producing or replacing a model binary, update its DVC pointer:

```bash
uv run dvc add artifacts/models/relevance/tfidf_logistic_noise_assigned/tfidf_logistic_noise_assigned.joblib
git add artifacts/models/relevance/tfidf_logistic_noise_assigned/manifest.json
git add artifacts/models/relevance/tfidf_logistic_noise_assigned/tfidf_logistic_noise_assigned.joblib.dvc
```

No shared DVC remote is configured yet. Configure one before relying on
`uv run dvc push` or `uv run dvc pull` across machines.

## Docker Compose

Build and start the long-lived services in the foreground:

```bash
docker compose up --build
```

Start the long-lived services in the background:

```bash
docker compose up -d --build
```

Check running services:

```bash
docker compose ps
```

Stop services but keep named volumes:

```bash
docker compose down
```

Restart one service after a config or code change:

```bash
docker compose restart backend
docker compose restart frontend
```

Default ports:

- frontend: <http://localhost:3000>
- backend: <http://localhost:8000/healthz>
- postgres: `localhost:5432`
- qdrant: <http://localhost:6333>

## Logs

Show recent logs for all services:

```bash
docker compose logs --tail 100
```

Follow all logs:

```bash
docker compose logs --follow
```

Follow one service:

```bash
docker compose logs --follow backend
docker compose logs --follow frontend
docker compose logs --follow postgres
docker compose logs --follow qdrant
```

Show logs since a recent time window:

```bash
docker compose logs --since 10m backend
```

Useful debugging pattern:

```bash
docker compose ps
docker compose logs --tail 200 backend
docker compose logs --tail 200 postgres
```

Runtime logs are structured JSON where Python services use
`shkandal_common.logging`.

## Health Checks

Check backend health:

```bash
curl http://localhost:8000/healthz
```

Check Qdrant:

```bash
curl http://localhost:6333/
curl http://localhost:6333/collections
```

Check PostgreSQL readiness from inside Compose:

```bash
docker compose exec postgres pg_isready -U shkandal -d shkandal
```

## Database

Start only PostgreSQL:

```bash
docker compose up -d postgres
```

Open `psql` in the running PostgreSQL container:

```bash
docker compose exec postgres psql -U shkandal -d shkandal
```

Run a quick table check:

```bash
docker compose exec postgres psql -U shkandal -d shkandal -c '\dt'
```

PostgreSQL data is stored in the Compose `postgres-data` named volume. It
survives container restarts and `docker compose down`. To intentionally reset
local database state, remove volumes. This also removes Qdrant local data:

```bash
docker compose down -v
```

Run migrations from the repository root:

```bash
uv run alembic -c packages/database/alembic.ini upgrade head
uv run alembic -c packages/database/alembic.ini current
```

Inspect migration history:

```bash
uv run alembic -c packages/database/alembic.ini history
```

Create a new migration only after model changes:

```bash
uv run alembic -c packages/database/alembic.ini revision --autogenerate -m "describe change"
```

## Ingestion Worker

The ingestion worker is a one-shot job. Run one full ingestion pass locally:

```bash
docker compose --profile jobs run --rm worker-ingestion
```

Run one source with a small debug limit:

```bash
docker compose --profile jobs run --rm worker-ingestion python -m worker_ingestion.main --source pravda --limit 20
```

Run a bounded date range:

```bash
docker compose --profile jobs run --rm worker-ingestion python -m worker_ingestion.main --since 2025-01-01 --until 2025-01-31 --limit 100
```

Date-bounded runs use a higher backfill discovery cap by default so source
archive traversal is not truncated at the daily discovery limit.
For dense sources, raise the cap explicitly:

```bash
docker compose --profile jobs run --rm worker-ingestion python -m worker_ingestion.main --source pravda --since 2025-01-01 --until 2026-06-03 --max-backfill-urls-per-source 80000
```

`pravda`, `nabu`, `dbr`, `ssu`, `kmu`, and `president` requests use browser TLS
impersonation in the worker because the default Python HTTP client is blocked
or challenged by those sites from Docker. `pravda` also runs with a source-level
crawl delay to avoid 429 rate limits.

Repair missing `published_at` values from stored `raw_html` without refetching.
This command is a dry run unless `--apply` is included:

```bash
docker compose --profile jobs run --rm worker-ingestion python -m worker_ingestion.main --repair-missing-published-at --limit 1000
docker compose --profile jobs run --rm worker-ingestion python -m worker_ingestion.main --repair-missing-published-at --limit 1000 --apply
```

Validate configured discovery endpoints and sample extraction without mutating
the database:

```bash
uv run python apps/worker-ingestion/scripts/validate_sources.py --sample 2
```

Generate a read-only article coverage report by source and month. Coverage
reporting is local scripts-only tooling and is not copied into the production
worker image:

```bash
uv run python apps/worker-ingestion/scripts/article_coverage_report.py
uv run python apps/worker-ingestion/scripts/article_coverage_report.py --source tyzhden --since 2026-01-01 --until 2026-06-03
```

Failed article fetches retry after 1 hour, 6 hours, and then daily, stopping
after five total attempts. Inspect exhausted rows or explicitly reset them for
another retry sequence:

```bash
uv run python apps/worker-ingestion/scripts/reset_failed_fetches.py --source pravda
uv run python apps/worker-ingestion/scripts/reset_failed_fetches.py --source pravda --apply
```

## ML Worker

The ML worker is also a one-shot job. Each run enqueues missing
`classify_article` jobs and processes one bounded batch of classification and
article-card jobs:

```bash
docker compose --profile jobs run --rm worker-ml
```

### Smoke-test 10 article cards

Put a real Lapatonia key in the ignored LiteLLM env file. The tracked LiteLLM
configuration routes all aliases through the OpenAI-compatible Lapatonia API:

```bash
cp infra/litellm/.env.example infra/litellm/.env
# Edit infra/litellm/.env and set LAPATONIA_API_KEY=...
```

Start the required infrastructure and run migrations:

```bash
docker compose up -d postgres qdrant llm-proxy
uv run alembic -c packages/database/alembic.ini upgrade head
```

If the database has no articles, ingest a small source sample. Then run the ML
worker until relevant classifier rows exist:

```bash
docker compose --profile jobs run --rm worker-ingestion python -m worker_ingestion.main --source pravda --limit 50
docker compose --profile jobs run --rm worker-ml
```

Select up to ten relevant articles without cards and ensure their card jobs are
queued at high priority:

```bash
docker compose exec -T postgres psql -U shkandal -d shkandal <<'SQL'
WITH candidates AS (
    SELECT a.id
    FROM articles AS a
    JOIN article_relevance AS ar ON ar.article_id = a.id AND ar.is_relevant = true
    LEFT JOIN article_cards AS ac ON ac.article_id = a.id
    LEFT JOIN jobs AS j
      ON j.article_id = a.id
     AND j.job_type = 'create_article_card'
    WHERE ac.id IS NULL
      AND (j.id IS NULL OR j.status <> 'running')
    ORDER BY a.published_at DESC NULLS LAST, a.created_at DESC
    LIMIT 10
)
INSERT INTO jobs (id, job_type, article_id, status, priority, payload, max_attempts)
SELECT
    gen_random_uuid(),
    'create_article_card',
    id,
    'queued',
    100,
    jsonb_build_object('article_id', id::text),
    3
FROM candidates
ON CONFLICT (job_type, article_id) DO UPDATE
SET status = 'queued',
    priority = 100,
    attempt_count = 0,
    run_after = NULL,
    locked_at = NULL,
    locked_by = NULL,
    last_error = NULL,
    updated_at = now();
SQL
```

Run exactly one bounded worker batch of ten:

```bash
docker compose --profile jobs run --rm -e CLAIM_BATCH_SIZE=10 worker-ml
```

Inspect the generated rows and their LLM run history:

```bash
docker compose exec postgres psql -U shkandal -d shkandal -c \
  "SELECT id, job_type, article_id, status, attempt_count, last_error, updated_at FROM jobs ORDER BY updated_at DESC LIMIT 20;"

docker compose exec postgres psql -U shkandal -d shkandal -c \
  "SELECT id, article_id, llm_run_id, title_uk, summary_uk, card_json, created_at FROM article_cards ORDER BY created_at DESC LIMIT 10;"

docker compose exec postgres psql -U shkandal -d shkandal -c \
  "SELECT id, run_type, model_name, status, metadata, raw_output, repaired_output, error_message, created_at FROM llm_runs ORDER BY created_at DESC LIMIT 10;"
```

After changing the article-card prompt or JSON contract, preview and apply a
full card regeneration. Stop active ML workers first; apply mode also refuses
to proceed if any `create_article_card` job is running. Existing `llm_runs`
remain available for comparison and debugging:

```bash
uv run python -m worker_ml.reprocess_article_cards
uv run python -m worker_ml.reprocess_article_cards --apply
```

To regenerate the same ten most recently created existing cards for a
before/after comparison:

```bash
uv run python -m worker_ml.reprocess_article_cards --apply --limit 10
docker compose --profile jobs run --rm -e CLAIM_BATCH_SIZE=10 worker-ml
docker compose exec postgres psql -U shkandal -d shkandal -c \
  "SELECT article_id, is_case_candidate, card_json->>'noise_reason' AS noise_reason, title_uk, card_json FROM article_cards ORDER BY created_at DESC LIMIT 10;"
```

To route through another provider instead, add its credential to
`infra/litellm/.env` and change the LiteLLM model entries in
`infra/litellm/config.yaml.example` before starting `llm-proxy`.

For optional direct loop mode, bypass the scheduled one-shot runtime:

```bash
python -m worker_ingestion.main --loop
python -m worker_ml.main --loop
```

The ingestion heartbeat and healthcheck apply only to optional loop mode, not
to normal systemd-scheduled one-shot runs.

## Server Scheduling

On a Linux server, keep backend, frontend, PostgreSQL, Qdrant, the LiteLLM
proxy, and supporting infrastructure running as long-lived Compose services.
Systemd starts the one-shot workers with `docker compose run --rm`.

Install and start the timers from a checkout deployed at `/opt/shkandal`:

```bash
./ops/install-systemd.sh
systemctl list-timers "shkandal-*"
```

Ingestion runs hourly. ML runs every 70 minutes so scheduled passes do not
repeatedly probe a rolling hourly LLM quota. `llm-proxy` remains in Compose
because the ML pipeline uses it for article-card and resolution stages.
Manually trigger either job:

```bash
sudo systemctl start shkandal-ingestion.service
sudo systemctl start shkandal-ml-worker.service
```

Inspect recent job logs:

```bash
journalctl -u shkandal-ingestion.service -n 100 --no-pager
journalctl -u shkandal-ml-worker.service -n 100 --no-pager
```

## Frontend

The frontend is normally run through Compose. For direct local frontend checks:

```bash
cd apps/frontend
npm install
npm run lint
npm run build
```

The frontend reads `NEXT_PUBLIC_BACKEND_URL` from Compose and points at
`http://localhost:8000` by default.

## Common Recovery Commands

Rebuild images without using the build cache:

```bash
docker compose build --no-cache
```

Pull fresh base images:

```bash
docker compose pull
```

Remove stopped containers while keeping named volumes:

```bash
docker compose down --remove-orphans
```

Reset all local Compose state, including PostgreSQL and Qdrant data:

```bash
docker compose down -v --remove-orphans
```

Use reset commands only when the local data can be discarded.

## Current Scope

The repository currently starts service shells and infrastructure, includes the
initial PostgreSQL schema/migration layer, and implements curated media and
institutional article ingestion from configured sitemaps, RSS/Atom feeds, and
section pages. It does not yet implement classifier inference, LLM resolution,
Qdrant indexing, or public dossier pages.
