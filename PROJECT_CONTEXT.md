# Project Context

## Current Implemented State

Shkandal is scaffolded as a monorepo with Python service shells, a Next.js
frontend boundary, Docker Compose runtime infrastructure, shared config/logging,
and smoke tests.

## Service Map

- `backend`: FastAPI service exposing `GET /healthz`.
- `worker-ingestion`: async worker entrypoint for future article discovery and extraction.
- `worker-ml`: async worker entrypoint for future filtering, retrieval, embeddings, and LLM resolution.
- `frontend`: Next.js TypeScript app with an API health link.
- `postgres`: main relational database and future job store.
- `qdrant`: vector search index.

## Runtime Decisions

- Docker Compose is the default runtime entrypoint.
- PostgreSQL is the source of truth.
- Qdrant is rebuildable from PostgreSQL-backed data.
- Redis is excluded from MVP.
- LLM infrastructure is represented by environment variables only; no secrets are committed.

## Documentation Layout

- `docs/VISION.md`: product intent from the README.
- `docs/run-project.md`: local runtime instructions.
- `docs/system/README.md`: system overview.
- `docs/system/services/`: service boundary notes.
- `docs/system/foundation/`: config, logging, testing, and runtime foundation.

## Known Next Work

- Add database schema and migrations for Article, Case, Person, Event, CaseCard, CaseDigest, and jobs.
- Implement source configuration and article extraction.
- Add relevance, retrieval, LLM resolution, and human review workflows.
