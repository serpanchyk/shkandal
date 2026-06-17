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

## Local Observability

Start the normal long-lived app services first:

```bash
docker compose up -d --build
```

Start or rebuild the optional observability profile:

```bash
docker compose --profile observability up -d --build
```

The profile also starts its required app services when they are not already
running. Local endpoints:

- Grafana: <http://localhost:3001>, default login `admin` / `admin`
- Prometheus: <http://localhost:9090>
- Loki readiness/debugging: <http://localhost:3100/ready>
- Backend Prometheus metrics: <http://localhost:8000/metrics>

Grafana automatically provisions the `Shkandal Local Overview` dashboard and
Prometheus/Loki datasources. Use its log panels or Explore with queries such as:

```logql
{compose_service="backend"} | json
{compose_service="worker-ml"} | json
{compose_service="worker-ingestion"} | json
{compose_service=~"llm-proxy|postgres|qdrant"}
```

Backend request metrics include request rate, route-template latency, and 5xx
errors. Durable job metrics include counts by `job_type` and `status`, oldest
queued age, recent LLM run status counts, and active LLM cooldown expiry.

To debug stuck `worker-ml` work, check the dashboard's oldest queued age,
running/failed job panels, and worker logs. Then inspect durable rows directly:

```bash
docker compose exec postgres psql -U shkandal -d shkandal -c \
  "SELECT job_type, status, count(*), min(created_at), min(run_after), min(locked_at) FROM jobs GROUP BY job_type, status ORDER BY job_type, status;"
```

To debug provider failures or cooldowns, inspect the LLM error log panel and:

```bash
docker compose exec postgres psql -U shkandal -d shkandal -c \
  "SELECT scope, cooldown_kind, resume_at, reason FROM llm_cooldowns;"
docker compose exec postgres psql -U shkandal -d shkandal -c \
  "SELECT run_type, status, count(*) FROM llm_runs WHERE created_at >= now() - interval '24 hours' GROUP BY run_type, status;"
docker compose logs --tail 200 llm-proxy
```

Alloy reads the local Docker socket in read-only mode and captures container
standard output while it is running. Keep it running before starting one-shot
workers when their logs need to appear in Loki. Very short `docker compose run
--rm` jobs can be deleted by Docker before Alloy attaches. During local log
debugging, omit `--rm`, confirm the logs in Grafana, then remove the stopped
one-shot container.

To add monitoring for a new service, expose bounded Prometheus metrics or add a
real Blackbox probe in `infra/observability/prometheus/prometheus.yml`, keep
logs on standard output for Alloy discovery, and add only useful panels to the
provisioned overview dashboard. Do not use raw IDs, URLs, article text, or full
errors as metric labels.

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
./ops/run-migrations
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

Preview website icon discovery for stored Sources, then explicitly overwrite
frontend PNG assets and update `sources.logo_path`:

```bash
uv run python apps/worker-ingestion/scripts/sync_source_logos.py
uv run python apps/worker-ingestion/scripts/sync_source_logos.py --source pravda --apply
uv run python apps/worker-ingestion/scripts/sync_source_logos.py --apply
```

This is local scripts-only tooling because it writes to
`apps/frontend/public/sources/`.

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

To drain the full ML backlog before launch, including downstream jobs created
while processing, run explicit backfill mode:

```bash
docker compose --profile jobs run --rm worker-ml python -m worker_ml.main --backfill
```

Use repeatable `--job-type` flags to run selected stages only. For example, this
discovers relevant articles missing cards, drains their card jobs, and leaves
newly-created downstream resolution jobs queued:

```bash
docker compose --profile jobs run --rm worker-ml python -m worker_ml.main --backfill --job-type create_article_card
```

The filter also works with the default one-shot mode and `--loop`. Backfill
mode waits through deferred retries and provider cooldowns. A filtered backfill
exits based only on its selected job types; exhausted selected failures are
left in PostgreSQL for inspection and produce a nonzero exit code. A selected
stale running job that exhausted its final attempt is also reported as blocked
and produces a nonzero exit code instead of making backfill wait forever.

After fixing the cause, inspect exhausted jobs before explicitly requeueing
them. The recovery command is dry-run by default and does not modify successful
domain output:

```bash
docker compose --profile jobs run --rm worker-ml python -m worker_ml.recover_failed_jobs --job-type update_case_copy
docker compose --profile jobs run --rm worker-ml python -m worker_ml.recover_failed_jobs --job-type update_case_copy --error-contains Qdrant --limit 12 --apply
```

### Smoke-test 10 article cards

Put real Lapatonia credentials in the ignored LiteLLM env file. AWS credentials
are optional while Bedrock fallback routing is disabled. The
tracked LiteLLM configuration routes all logical aliases through one shared
OpenAI-compatible Lapatonia deployment with a combined 60 RPM limit and falls
back to no secondary provider when a primary request fails. The Amazon Bedrock
Gemma 3 27B model entry and credential settings are retained for optional direct
testing or future reactivation. After four Lapatonia failures within one hour,
every alias remains unavailable for one hour. The cooldown is in memory, so
restarting `llm-proxy` clears it:

```bash
cp infra/litellm/.env.example infra/litellm/.env
# Edit infra/litellm/.env and set:
# LAPATONIA_API_KEY=...
# AWS_ACCESS_KEY_ID=...
# AWS_SECRET_ACCESS_KEY=...
# AWS_REGION=us-west-2
```

The AWS identity needs `bedrock:InvokeModel` and
`bedrock:InvokeModelWithResponseStream` permissions for
`google.gemma-3-27b-it`. Enable model access for Gemma 3 27B in the selected
Bedrock region before starting the proxy. When using temporary AWS credentials,
also add `AWS_SESSION_TOKEN` to `infra/litellm/.env`.

Start the required infrastructure and run migrations:

```bash
docker compose up -d postgres qdrant llm-proxy
./ops/run-migrations
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

To route through another provider, add its credential to `infra/litellm/.env`
and change the LiteLLM model entries or fallback routing in
`infra/litellm/config.yaml.example` before starting `llm-proxy`.

For optional direct loop mode, bypass the scheduled one-shot runtime:

```bash
python -m worker_ingestion.main --loop
python -m worker_ml.main --loop
```

The ingestion heartbeat and healthcheck apply only to optional loop mode, not
to normal systemd-scheduled one-shot runs.

## Systemd Scheduling

On a Linux server, keep backend, frontend, PostgreSQL, Qdrant, the LiteLLM
proxy, and supporting infrastructure running as long-lived Compose services.
Systemd starts one-shot workers through `ops/run-scheduled-worker`, which uses
deterministic container names, prevents overlap, and force-removes the
scheduled container on exit, interruption, or systemd timeout.
The installers stop existing worker units and remove auto-named Compose worker
one-offs; explicitly named backfill containers are left untouched.

### Deploy And Start Scheduled Workers

After pulling worker, migration, or systemd changes, run these commands from the
project checkout in order:

```bash
# Start PostgreSQL and wait until it is healthy before applying migrations.
docker compose up -d --wait postgres

# Apply pending schema migrations before workers use the new code.
./ops/run-migrations

# Start or rebuild all long-lived services after migrations succeed.
docker compose up -d --build

# Install the current units and start both scheduled timers.
./ops/install-systemd.sh
```

Applying migrations preserves existing database contents unless a specific
migration explicitly documents otherwise. Migration `202606120003` makes
`jobs.article_id` nullable so Case-scoped jobs can be inserted.

Verify the services, timers, and latest worker logs:

```bash
docker compose ps
systemctl list-timers "shkandal-*"
journalctl -u shkandal-ml-worker.service -n 100 --no-pager
journalctl -u shkandal-ingestion.service -n 100 --no-pager
```

To run both workers immediately instead of waiting for their next timer
activation:

```bash
sudo systemctl start shkandal-ingestion.service
sudo systemctl start shkandal-ml-worker.service
```

Install and start the timers from the checkout that should run the workers:

```bash
./ops/install-systemd.sh
systemctl list-timers "shkandal-*"
```

The installer renders each service with the current checkout's absolute path,
so the same command works for `/opt/shkandal` deployments and local development
checkouts. Moving the checkout requires running the installer again.

For a local PC without system-wide sudo installation, install user systemd
timers instead:

```bash
./ops/install-user-systemd.sh
systemctl --user list-timers "shkandal-*"
loginctl enable-linger "$USER"
```

User timers run while the user's systemd session is active. User lingering keeps
that session and its timers running while the user is logged out and after
reboot.

Ingestion runs every even-numbered hour. ML runs five minutes after the previous
pass becomes inactive and exits immediately while a durable LLM cooldown is
active. `llm-proxy` remains in Compose because the ML pipeline uses it for
article-card and resolution stages.

Manage system-wide server timers:

```bash
systemctl list-timers "shkandal-*"
sudo systemctl start shkandal-ingestion.service
sudo systemctl start shkandal-ml-worker.service
sudo systemctl disable --now shkandal-ingestion.timer shkandal-ml-worker.timer
```

Manage local-PC user timers:

```bash
systemctl --user list-timers "shkandal-*"
systemctl --user start shkandal-ingestion.service
systemctl --user start shkandal-ml-worker.service
systemctl --user disable --now shkandal-ingestion.timer shkandal-ml-worker.timer
```

Inspect system-wide server logs:

```bash
journalctl -u shkandal-ingestion.service -n 100 --no-pager
journalctl -u shkandal-ml-worker.service -n 100 --no-pager
```

Inspect or follow local-PC user logs:

```bash
journalctl --user -u shkandal-ingestion.service -n 100 --no-pager
journalctl --user -u shkandal-ml-worker.service -f
```

## Frontend

The frontend source is under `apps/frontend`. It is normally run with the
backend through Compose:

```bash
docker compose up --build frontend
```

Open <http://localhost:3000>. Compose starts the required backend and maps
server-side frontend requests to `http://backend:8000`; browser-side view
counting uses <http://localhost:8000>.

For direct frontend development, start a backend at <http://localhost:8000>,
then run:

```bash
cd apps/frontend
npm install
npm run dev
```

Open <http://localhost:3000>. For direct local frontend checks:

```bash
cd apps/frontend
npm install
npm run lint
npm run build
```

The frontend uses `BACKEND_INTERNAL_URL` for server rendering,
`NEXT_PUBLIC_BACKEND_URL` for browser requests, and `NEXT_PUBLIC_SITE_URL` for
metadata and sitemap URLs. All default to local development URLs.

Playwright tests write a deterministic public graph. Run them only against an
isolated disposable PostgreSQL database:

```bash
cd apps/frontend
npm run test:e2e
```

CI provisions the isolated database, applies migrations, seeds the graph,
starts the backend, and runs Playwright automatically.

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

The repository implements curated media and institutional ingestion, relevance
classification, LLM article cards and Case/Entity/Event resolution, the
PostgreSQL evidence graph, the FastAPI public reader API, and server-rendered
public feed, Case, and Entity pages. Qdrant indexing and retrieval remain
planned work.
