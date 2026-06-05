# Project Context

## Current Implemented State

Shkandal is scaffolded as a monorepo with Python service shells, a Next.js
frontend boundary, Docker Compose runtime infrastructure, shared config/logging,
an async SQLAlchemy database package, Alembic migrations, smoke tests, and a
curated source ingestion worker.

The implemented code includes the MVP PostgreSQL schema and migration layer plus
initial media and institutional article discovery/fetch/extraction/storage,
date-bounded high-cap backfills, stored-HTML publication-date repair, and the
first article relevance classifier job handler. LLM prompts and public
case/entity pages are future work. The LLM task architecture now exists in
`worker-ml`, with LangChain prompt/chaining support and LiteLLM proxy routing,
but downstream article-card and resolution jobs are not fully wired yet.

## Product Direction

Shkandal is a Ukrainian-only public product for Ukraine. It turns Ukrainian
media and institutional source articles into reader-facing dossiers about
public scandals, corruption investigations, political cases, institutional
decisions, and socially important stories.

The MVP is automatic publishing after an initial curated one-year backfill. Human
review and correction tooling are later quality layers, not blocking MVP stages.

## Service Map

- `backend`: FastAPI service exposing `GET /healthz` today; future public API and business boundary.
- `worker-ingestion`: curated media and institutional source discovery from sitemaps, RSS/Atom feeds, and section pages; date-bounded backfill traversal; fetching; generic-first extraction; publication-date repair from stored raw HTML; URL identity normalization; image URL extraction; and PostgreSQL upsert.
- `worker-ml`: async worker entrypoint with article relevance classifier job enqueueing/handling, E5-small embedding service, Qdrant vector-index integration, and the LLM task architecture for future article cards, resolution, and deduplication.
- `frontend`: Next.js TypeScript app with an API health link today; future public feed, case pages, and entity pages.
- `postgres`: source-of-truth database and Postgres-backed job store schema.
- `packages/database`: shared async SQLAlchemy models, session helpers, and Alembic migrations.
- `qdrant`: rebuildable 384-dimensional vector indexes for cases, entities, and events.

## Runtime Decisions

- Docker Compose is the default runtime entrypoint.
- PostgreSQL is the source of truth and persists locally through the Compose
  `postgres-data` named volume.
- Qdrant is rebuildable from PostgreSQL-backed data.
- Redis is excluded from MVP.
- One generic PostgreSQL `jobs` table with row locking is the MVP background-work mechanism. A job is one durable, retryable, typed pipeline work unit, not a worker process or domain object.
- MVP jobs are article-scoped: each job works on one article, so the job store should carry an explicit `article_id` and enforce one all-time job row per `(job_type, article_id)`. Reruns reset or requeue that row rather than creating duplicates.
- Ingestion is not queued as a job in the MVP. After historical backfill, the ingestion worker should run continuously, discover new articles, and persist them to PostgreSQL; downstream ML processing consumes stored articles through jobs.
- `worker-ml` owns ML job creation. It should poll PostgreSQL for articles missing ML-derived state, starting with articles missing `article_relevance`, and enqueue idempotent downstream jobs such as `classify_article`.
- Article jobs are gated by durable outputs. Each successful step enqueues the next step only after its output row/link exists; downstream jobs are not pre-enqueued.
- Workers claim jobs with PostgreSQL `FOR UPDATE SKIP LOCKED` row locking so multiple workers do not process the same job.
- `running` jobs are reclaimable leases. If `locked_at` becomes older than the configured stale-job timeout, defaulting to 30 minutes, another worker may retry the job.
- Claiming a job increments `attempt_count`; crashes count as attempts. Failed jobs with attempts remaining return to `queued` with `run_after`, and exhausted jobs become `failed`.
- LLM calls go through a LiteLLM proxy service. `worker-ml` uses logical per-stage aliases, while provider credentials, throttling, and routing belong to proxy configuration. No secrets are committed.
- DVC tracks large local model binaries under `artifacts/models/`; Git tracks
  manifests and `.dvc` pointer files. No shared DVC remote is configured yet.

## Domain Decisions

- A `Case` is a reader-facing dossier/topic, not an exclusive article cluster.
- One relevant article is enough to create a public case.
- Articles, entities, and events can connect to multiple cases.
- Articles can link to cases even when they do not create extracted events.
- `case_entities` and `case_events` are direct materialized links for public pages, created from article-level resolution plus article-case context.
- `Entity` is one global typed table for people, organizations, institutions, companies, political parties, informal groups, and unknown actors.
- `Event` is a global strict real-world occurrence, shared across cases when appropriate.
- Event relations are out of MVP.
- Direct entity-event relations are out of MVP.
- Public article cards link directly to original source pages; Shkandal does not publish copied full article pages.
- Remote image URLs are stored, but images are not cached/proxied in MVP.
- Generated public content is Ukrainian and neutral/factual.

## Documentation Layout

- `README.md`: project compass and product/system decisions.
- `docs/VISION.md`: concise product vision.
- `docs/PRD.md`: synthesized PRD for the automatic dossier MVP.
- `docs/run-project.md`: local runtime instructions.
- `docs/system/README.md`: system overview.
- `docs/system/services/`: service boundary notes.
- `docs/system/foundation/`: config, logging, database, testing, and runtime foundation.

## Known Next Work

- Wire article-card and resolution jobs to the LLM task architecture.
- Implement Qdrant collections for case, entity, and event cards.
- Build public API and frontend for homepage feed, case pages, and entity pages.
