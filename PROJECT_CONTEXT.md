# Project Context

## Current Implemented State

Shkandal is scaffolded as a monorepo with Python service shells, a Next.js
frontend boundary, Docker Compose runtime infrastructure, shared config/logging,
and smoke tests.

The implemented code is still foundation-only. The article pipeline, database
schema, classifier, LLM prompts, and public case/entity pages are future work.

## Product Direction

Shkandal is a Ukrainian-only public product for Ukraine. It turns Ukrainian
media and institutional source articles into reader-facing dossiers about
public scandals, corruption investigations, political cases, institutional
decisions, and socially important stories.

The MVP is automatic publishing after an initial curated one-year backfill. Human
review and correction tooling are later quality layers, not blocking MVP stages.

## Service Map

- `backend`: FastAPI service exposing `GET /healthz` today; future public API and business boundary.
- `worker-ingestion`: async worker entrypoint for future source discovery, fetching, extraction, normalization, and image URL extraction.
- `worker-ml`: async worker entrypoint for future binary relevance classification, article cards, embeddings, Qdrant retrieval, LLM resolution, and deduplication.
- `frontend`: Next.js TypeScript app with an API health link today; future public feed, case pages, and entity pages.
- `postgres`: source-of-truth database and future Postgres-backed job store.
- `qdrant`: rebuildable vector indexes for cases, entities, and events.

## Runtime Decisions

- Docker Compose is the default runtime entrypoint.
- PostgreSQL is the source of truth.
- Qdrant is rebuildable from PostgreSQL-backed data.
- Redis is excluded from MVP.
- One generic PostgreSQL `jobs` table with row locking is the MVP background-work mechanism.
- LLM infrastructure is represented by environment variables only; no secrets are committed.
- DVC is planned when classifier training code and artifacts land, not before.

## Domain Decisions

- A `Case` is a reader-facing dossier/topic, not an exclusive article cluster.
- Articles, entities, and events can connect to multiple cases.
- `case_entities` and `case_events` are direct materialized links for public pages, created from article-level resolution plus article-case context.
- `Entity` is one global typed table for people, organizations, institutions, companies, political parties, informal groups, and unknown actors.
- `Event` is a global strict real-world occurrence, shared across cases when appropriate.
- Event relations are out of MVP.
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
- `docs/system/foundation/`: config, logging, testing, and runtime foundation.

## Known Next Work

- Add database schema and migrations for sources, articles, cases, entities, events, links, LLM runs, jobs, and counters.
- Implement curated source configuration and article extraction with raw HTML/text/image URL storage.
- Add local binary relevance classifier interface and persistence of classifier decisions.
- Add Ukrainian prompt files and Pydantic-validated LLM contracts.
- Implement Qdrant collections for case, entity, and event cards.
- Build public API and frontend for homepage feed, case pages, and entity pages.
