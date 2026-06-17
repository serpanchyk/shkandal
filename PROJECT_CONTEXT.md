# Project Context

## Current Implemented State

Shkandal is scaffolded as a monorepo with Python service shells, a Next.js
frontend boundary, Docker Compose runtime infrastructure, shared config/logging,
an async SQLAlchemy database package, Alembic migrations, deterministic tests,
and a curated source ingestion worker.

The implemented code includes the MVP PostgreSQL schema and migration layer plus
initial media and institutional article discovery/fetch/extraction/storage,
date-bounded high-cap backfills, stored-HTML publication-date repair, and the
first article relevance classifier job handler. The LLM task architecture exists
in `worker-ml`, with LangChain prompt/chaining support and LiteLLM proxy
routing. Entity and Event resolution jobs run after Case resolution. Public
Case and Entity data is exposed through a FastAPI API and rendered by the
server-rendered Next.js frontend.

## Product Direction

Shkandal is a Ukrainian-only public product for Ukraine. It turns Ukrainian
media and institutional source articles into reader-facing dossiers about
public scandals, corruption investigations, political cases, institutional
decisions, and socially important stories.

The MVP is automatic publishing after an initial curated one-year backfill. Human
review and correction tooling are later quality layers, not blocking MVP stages.

## Service Map

- `backend`: FastAPI public API and application query boundary for feed, Case,
  Entity, sitemap, and anonymous Case-view contracts.
- `worker-ingestion`: two-hourly systemd-scheduled one-shot curated-source discovery from sitemaps, RSS/Atom feeds, and section pages; bounded fetch retries; date-bounded backfill traversal; fetching; generic-first extraction; publication-date repair from stored raw HTML; URL identity normalization; image URL extraction; and PostgreSQL upsert.
- `worker-ml`: async worker entrypoint with article relevance, article cards,
  Case resolution/copy, and article-scoped global Entity/Event resolution.
- `frontend`: server-rendered Next.js public feed, Case pages, Entity pages,
  provenance interactions, metadata, and sitemap.
- `postgres`: source-of-truth database and Postgres-backed job store schema.
- `packages/database`: shared async SQLAlchemy models, session helpers, and Alembic migrations.
- `qdrant`: rebuildable 384-dimensional vector indexes for cases, entities, and events.

## Runtime Decisions

- Docker Compose is the default runtime entrypoint.
- An optional local Compose `observability` profile provides provisioned
  Grafana, Prometheus, Loki, Alloy log collection, and real service health
  probes. It does not change production scheduling or worker lifetimes.
- Systemd timers schedule one-shot ingestion and ML worker containers on servers.
- PostgreSQL is the source of truth and persists locally through the Compose
  `postgres-data` named volume.
- Qdrant is rebuildable from PostgreSQL-backed data.
- Redis is excluded from MVP.
- One generic PostgreSQL `jobs` table with row locking is the MVP background-work mechanism. A job is one durable, retryable, typed pipeline work unit, not a worker process or domain object.
- Jobs have exactly one typed article or Case subject. Article jobs are unique by
  `(job_type, article_id)`; revision-aware Case jobs are unique by
  `(job_type, case_id)`.
- Active Cases enter an automatic ordered Case Audit Pipeline after evidence
  changes and after a configurable 30-day fallback interval. Coherence audits
  preserve relevant repetition, split mixed stories, or detach evidence that
  belongs to no concrete story. Public-interest audits permanently hide
  unsuitable dossiers, and duplicate audits resolve internal candidate pairs.
- Ingestion is not queued as a job in the MVP. After historical backfill, systemd starts a one-shot full-source pass every two hours that persists new articles to PostgreSQL and retries failed fetches up to five attempts.
- `worker-ml` owns ML job creation. It polls PostgreSQL for articles missing
  `article_relevance`, enqueues idempotent `classify_article` jobs, and processes
  relevant articles through `create_article_card` into `article_cards` with
  `llm_runs` provenance. Article cards apply a stricter LLM case-candidate gate;
  non-case cards retain a summary but do not expose events, entities, or case
  signature terms. Prompt-facing schemas omit enum constraints and request a
  concise decision basis before categorical choices; runtime contracts remain
  strict. Conservative deterministic normalization is recorded as repaired LLM
  provenance without changing raw provider output, and now truncates only
  whitelisted bounded diagnosis and decision-summary strings to their runtime
  max lengths when verbose model wording would otherwise fail validation.
- Article jobs are gated by durable outputs. Each successful step enqueues the next step only after its output row/link exists; downstream jobs are not pre-enqueued.
- Case resolution is now two-stage for existing Cases: the first LLM pass
  matches against retrieved Case cards, and each provisional existing-Case link
  then goes through an inline second pass against that Case's linked Article
  Cards before any `case_articles` row is written. Inconclusive second-pass
  checks are dropped, not preserved.
- Workers claim jobs with PostgreSQL `FOR UPDATE SKIP LOCKED` row locking so multiple workers do not process the same job.
- `running` jobs are reclaimable leases. If `locked_at` becomes older than the configured stale-job timeout, defaulting to 30 minutes, another worker may retry the job.
- `worker-ml` uses weighted fair scheduling and four concurrent execution slots
  by default. Case, Entity, and Event mutation namespaces remain independently
  serialized, and stale pending LLM runs are failed during worker startup.
- `worker-ml` accepts repeatable `--job-type` filters in one-shot, loop, and
  backfill modes. Enabled classification and article-card stages discover
  missing durable jobs; filtered backfills drain and report only selected job
  types while leaving unselected downstream work queued.
- Claiming a job increments `attempt_count`; crashes count as attempts. Failed jobs with attempts remaining return to `queued` with `run_after`, and exhausted jobs become `failed`.
- Qdrant failures remain retryable job failures and include operation,
  collection, and point context where available. Persisted job errors are never
  empty. An explicit dry-run-first worker-ML recovery command can requeue
  selected exhausted failures without changing successful domain output.
- LLM calls go through a pinned LiteLLM proxy service. `worker-ml` uses logical per-stage aliases, while provider credentials, throttling, and routing belong to proxy configuration. The tracked proxy configuration maps every alias to one shared Lapathoniia deployment with a combined 60 RPM limit and retries transient timeout/internal-server failures once. The Amazon Bedrock Gemma 3 27B model entry is retained but is not configured as a fallback. Four Lapathoniia failures within one hour start a shared one-hour in-memory cooldown; restarting `llm-proxy` clears it. No secrets are committed.
- Provider HTTP `429` responses that remain after LiteLLM routing
  create a shared durable LLM cooldown. The current LLM job is deferred without
  consuming an attempt and the ML pass exits.
  Explicit `Retry-After` values are honored; the first ambiguous response waits
  five minutes and a second within 15 minutes infers a one-hour cooldown.
  Other provider errors remain per-job failures.
- Runtime configuration uses three ignored env files: root `.env` for shared
  application settings and proxy access, `infra/postgres/.env` for PostgreSQL
  bootstrap credentials, and `infra/litellm/.env` for provider API keys.
- A separate `docker-compose.prod.yaml` provides the minimal public-web server
  deployment. It runs only `caddy`, `frontend`, `backend`, `postgres`, and a
  one-shot `migrate` job; only Caddy publishes ports `80` and `443`.
- Production runtime configuration uses root `.env.production` for public-web
  settings and `infra/postgres/.env.production` for PostgreSQL bootstrap
  credentials. Caddy serves `:80` when `PUBLIC_HOSTNAME` is empty and switches
  to hostname-based managed HTTPS when it is set.
- DVC tracks large local model binaries under `artifacts/models/`; Git tracks
  manifests and `.dvc` pointer files. No shared DVC remote is configured yet.

## Domain Decisions

- A `Case` is a reader-facing dossier/topic, not an exclusive article cluster.
- A `Case` follows one durable public-interest story across procedural stages.
- Similar routine incidents do not form a broad systemic Case without one
  concrete shared scheme, investigation, decision, or causal chain.
- Case relations are symmetric `related` or `possible_duplicate` links.
- One relevant article is enough to create a public case.
- Articles, entities, and events can connect to multiple cases.
- Case resolution can explicitly reject a case-candidate article without
  creating domain records; the decision remains auditable through its LLM run.
- Existing-Case links are persisted only after a second card-based coherence
  recheck against the chosen Case's current evidence.
- A Case Split preserves the dominant story on the original Case and creates
  new Cases for other coherent stories. A coherence audit preserves relevant
  repetition and may detach Article links that belong to no concrete story.
- Hidden Cases are terminal and retain their complete internal dossier.
- Duplicate merges preserve the Case with the most evidence, redirect absorbed
  slugs, and resolve candidates from explicit relations or substantial shared
  Article overlap.
- Articles can link to cases even when they do not create extracted events.
- `case_entities` and `case_events` are direct materialized links for public pages, created from article-level resolution plus article-case context.
- `Entity` is one global typed table for people, organizations, institutions, companies, political parties, informal groups, and unknown actors.
- `Event` is a global strict real-world occurrence, shared across cases when appropriate.
- Entity and Event identity mutations use separate advisory locks. Accepted
  items must be assigned to at least one linked Case; rejected provisional
  items are explicit.
- Event occurrence dates use separate year/month/day fields so partial and
  unknown dates do not create fictional exact dates.
- Event relations are out of MVP.
- Direct entity-event relations are out of MVP.
- Public article cards link directly to original source pages; Shkandal does not publish copied full article pages.
- Remote image URLs are stored, but images are not cached/proxied in MVP.
- Curated Source logo asset paths use `/sources/{source-slug}.png` in
  PostgreSQL; logo files are served from frontend-owned public assets.
- A local dry-run-first ingestion script discovers website raster icons,
  normalizes them to PNG, and updates Source logo assets and paths on apply.
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

- Implement Qdrant collections for case, entity, and event cards.
- Provision an isolated local browser-test database workflow; CI already runs
  browser-level public-reader coverage against deterministic seeded PostgreSQL.
