# Postgres

PostgreSQL is the source of truth for all durable application data. The local
runtime is the `postgres` Docker Compose service backed by the `postgres-data`
named volume.

The backend `/metrics` endpoint performs read-only aggregate queries against
`jobs`, `llm_runs`, and `llm_cooldowns` for local Prometheus monitoring. No
observability-specific durable tables are required.

Implemented MVP data areas:

- sources and source types;
- articles, extracted text, raw HTML, language, identity URLs, and remote image metadata;
- binary relevance decisions and classifier versions;
- provisional article cards;
- reader-facing cases;
- article-case links;
- immutable duplicate-pair audit results;
- global typed entities with aliases and Ukrainian descriptions;
- article-entity links;
- article-entity-case scoped relevance links;
- materialized case-entity links;
- global strict real-world events;
- article-event links;
- article-event-case scoped relevance links;
- materialized case-event links;
- LLM runs, prompt versions, model names, statuses, raw output, and repair attempts;
- one generic jobs table for Postgres-backed background work;
- anonymous aggregate case view counters.

`case_articles` does not need primary/secondary/background roles in the MVP.
`case_entities` and `case_events` carry the direct public-page links. Direct
entity-event relationship modeling is out of scope for MVP.

Event occurrence dates are stored as nullable year/month/day components plus
precision. Unknown dates remain unknown; publication timestamps are retained on
supporting Articles rather than copied into Events. Article Entity/Event links
carry LLM provenance and confidence, while Case-scoped links carry relevance
reasons; source text fragments are not duplicated into these link tables.

Generated public fields are overwritten in place for MVP. Store enough version
metadata to debug and manually reprocess later, but do not build automatic
snapshot/version infrastructure yet.

The shared `packages/database` workspace package owns the async SQLAlchemy
models, session helpers, and Alembic migrations. Run migrations from the
repository root:

```bash
./ops/run-migrations
uv run alembic -c packages/database/alembic.ini current
```

Local database data survives container restarts and `docker compose down`.
Use `docker compose down -v` only when intentionally deleting the local
PostgreSQL volume.
