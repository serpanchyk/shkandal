# Runtime

Docker Compose is the default runtime boundary.

Runtime dependencies:

- PostgreSQL 16 for durable application data.
- Qdrant for rebuildable case, entity, and event vector indexes.

Local PostgreSQL uses the Compose `postgres-data` named volume, so data survives
container restarts and `docker compose down`. Use `docker compose down -v` only
when intentionally resetting local database state.

Redis is intentionally excluded from the MVP. Background work can start with a
single generic PostgreSQL jobs table and row locking.

A job is one durable, retryable, typed pipeline work unit with a structured
payload. It is not a worker process and not a domain object. MVP jobs are
article-scoped: each job works on one article, and the job store should carry an
explicit article reference. Job enqueueing should be idempotent by enforcing one
job per `(job_type, article_id)` for the lifetime of the row, regardless of job
status. A job row represents that article's lifecycle through that pipeline
step. Reruns should reset or requeue the existing job, or introduce deliberate
versioned job semantics later, rather than accumulating duplicate job rows.
Durable output tables such as `article_relevance`, `article_cards`, and
`llm_runs` hold processing results and history; `jobs` coordinates work.
Initial job types are expected to cover downstream article processing, such as
relevance classification, article-card creation, case resolution, entity
resolution, and event resolution.

Article jobs form a gated chain. Each job should enqueue the next job only after
its own durable output exists. `classify_article` succeeds by writing
`article_relevance`; relevant articles then get `create_article_card`.
`create_article_card` succeeds by writing `article_cards`; it then enqueues
`resolve_article_cases`. After case links exist, the worker can enqueue
`resolve_article_entities` and `resolve_article_events`. Later jobs are not
pre-enqueued because they depend on upstream outputs and relevance gates.

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

Ingestion is not modeled as a queued job for the MVP. After the historical
backfill is complete, the ingestion worker should run continuously, discover new
articles, and write them to PostgreSQL. Downstream workers then enqueue or claim
processing jobs for stored articles.

The ML worker owns ML job creation. Ingestion only persists article evidence; it
does not need to know classifier, prompt, embedding, or resolution job types.
`worker-ml` should poll PostgreSQL for articles missing ML-derived state and
enqueue idempotent downstream jobs, starting with one `classify_article` job for
each article missing `article_relevance`.

The first public launch should happen after a curated one-year backfill reaches
a ready-enough checkpoint. After launch, pages update automatically from current
database rows.
