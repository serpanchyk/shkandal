# Runtime

Docker Compose is the default runtime boundary. On servers, systemd timers
schedule the one-shot ingestion and ML worker containers.

For the public web, the repo also ships a separate
`docker-compose.prod.yaml` deployment that runs only `caddy`, `frontend`,
`backend`, `postgres`, and a one-shot `migrate` job. Only Caddy publishes
network ports, exposing `80` and `443`; backend, frontend, and PostgreSQL stay
on the internal Compose network.

Remote production workers are intentionally local to this workstation, not
installed on the production VM. `docker-compose.worker-remote.yaml` runs
`worker-ingestion` or `worker-ml` against production PostgreSQL through
`ops/run-db-tunnel`, with the container database URL pointing at
`host.docker.internal:15433`.

Production deploys run over SSH to the existing Droplet checkout. GitHub
Actions validates the repo first, then runs `ops/deploy-production` in the
server repository. Production env files remain on the Droplet and are not copied
into CI.

Runtime dependencies:

- PostgreSQL 16 for durable application data.
- Qdrant for rebuildable case, entity, and event vector indexes.
- Optional local Grafana, Prometheus, Loki, Alloy, and Blackbox Exporter
  services under the Compose `observability` profile.

Local PostgreSQL uses the Compose `postgres-data` named volume, so data survives
container restarts and `docker compose down`. Use `docker compose down -v` only
when intentionally resetting local database state.

Redis is intentionally excluded from the MVP. Background work can start with a
single generic PostgreSQL jobs table and row locking.

A job is one durable, retryable, typed pipeline work unit with a structured
payload. It is not a worker process and not a domain object. A job has exactly
one typed subject: `article_id` or `case_id`. Article jobs remain unique by
`(job_type, article_id)`; case jobs are unique by `(job_type, case_id)` and use
requested/completed revisions so triggers arriving during a run are not lost.
Durable output tables such as `article_relevance`, `article_cards`, and
`llm_runs` hold processing results and history; `jobs` coordinates work.
LLM calls are routed through the LiteLLM proxy service in Compose. The proxy is
infrastructure for provider access, throttling, and routing; PostgreSQL remains
the source of truth for run history and generated data.
Initial job types are expected to cover downstream article processing, such as
relevance classification, article-card creation, case resolution, entity
resolution, and event resolution.

Article jobs form a gated chain. Each job should enqueue the next job only after
its own durable output exists. `classify_article` succeeds by writing
`article_relevance`; relevant articles then get `create_article_card`.
`create_article_card` succeeds by writing `article_cards`; it then enqueues
`resolve_article_cases`. That stage first matches against retrieved Case cards,
then rechecks each provisional existing-Case link against the selected Case's
linked Article Cards before persisting any `case_articles` rows. If every
provisional existing-Case link is dropped by that audit and the original
resolution did not already create a new Case, the worker runs a dedicated
new-Case fallback prompt under the `case_resolution` run type. A resolved
fallback creates a Case normally; a rejected fallback leaves the article
unconnected and does not enqueue downstream work. After case links exist, the
worker can enqueue
`resolve_article_entities` and `resolve_article_events`. Later jobs are not
pre-enqueued because they depend on upstream outputs and relevance gates.

Case identity resolution and case-copy updates share one PostgreSQL advisory
lock. If unavailable, the job is deferred without consuming an attempt. Affected
Case vectors are upserted before PostgreSQL commits; Qdrant failure rolls back
the Case mutation.

Entity and Event resolution use separate advisory locks for their respective
global identity namespaces. They may run concurrently with each other, while
each namespace remains serialized to prevent retrieve-before-create duplicate
identities.

Workers claim queued jobs through PostgreSQL row locking, using
`FOR UPDATE SKIP LOCKED` semantics. A worker claims eligible queued jobs ordered
by priority and age, marks them `running`, sets `locked_by` and `locked_at`, and
then processes them. Locked rows are skipped by other workers, so multiple
worker instances can run without processing the same job.

`running` jobs are leases, not permanent ownership. If a worker crashes, another
worker may reclaim a `running` job after its `locked_at` timestamp is older than
the configured stale-job timeout. The MVP default stale-job timeout is 30
minutes: long enough for classifier and moderate LLM work, short enough for
crashed jobs to recover the same day. Long LLM calls may later need a heartbeat
or a longer timeout, but the MVP recovery model is lease timeout reclamation.

Claiming a job consumes an attempt. Workers increment `attempt_count` when they
claim a job, before running job-specific code, so crashes still count toward the
retry limit. A successful attempt marks the job `succeeded`. A failed attempt
with attempts remaining returns the job to `queued` with a future `run_after`.
Retries use exponential-style backoff with jitter, starting from 1 minute, then
5 minutes, then 15 minutes for MVP defaults. When attempts are exhausted, the
job is marked `failed`.

Provider HTTP `429` responses are capacity deferrals, not job failures. The
worker records one shared durable LLM cooldown, releases the current LLM job
with its claim attempt restored, and sets its `run_after` to the cooldown
expiry, then ends the current pass. A pass exits before loading models,
enqueueing, or claiming jobs while the cooldown remains active. Explicit
`Retry-After` values below 30 minutes are short provider backoffs and longer
values are confirmed long cooldowns. Without a usable value, the first `429`
waits five minutes and a second within 15 minutes infers a one-hour cooldown.
HTTP errors other than `429`, connection errors, and invalid output remain
per-job failures so the batch can continue.

Ingestion is not modeled as a queued job for the MVP. After the historical
backfill is complete, systemd starts a one-shot full-source pass every two hours.
The pass retries failed fetches with bounded durable state and writes
successfully fetched articles to PostgreSQL. A separate systemd timer starts a
bounded ML pass five minutes after the previous pass becomes inactive.
Both worker CLIs default to one-shot execution. Optional `--loop` modes remain
available for direct/manual use. The ingestion heartbeat applies only to that
optional loop mode, not to the scheduled systemd runtime.

The ML worker also exposes an explicit finite `--backfill` mode. It repeatedly
plans and processes all supported ML jobs, waits through deferred retries and
shared provider cooldowns, and exits after no queued or running ML work remains.
Exhausted jobs are preserved for inspection and make the command exit nonzero.

The ML worker owns ML job creation. Ingestion only persists article evidence; it
does not need to know classifier, prompt, embedding, or resolution job types.
`worker-ml` should poll PostgreSQL for articles missing ML-derived state and
enqueue idempotent downstream jobs, starting with one `classify_article` job for
each article missing `article_relevance`.

The first public launch should happen after a curated one-year backfill reaches
a ready-enough checkpoint. After launch, pages update automatically from current
database rows.
