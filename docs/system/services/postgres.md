# Postgres

PostgreSQL is the source of truth for all durable application data.

Planned MVP data areas:

- sources and source types;
- articles, extracted text, raw HTML, language, canonical/normalized URLs, and remote image metadata;
- binary relevance decisions and classifier versions;
- provisional article cards;
- reader-facing cases;
- article-case links;
- explicit case relations;
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

Generated public fields are overwritten in place for MVP. Store enough version
metadata to debug and manually reprocess later, but do not build automatic
snapshot/version infrastructure yet.

The current scaffold only starts the database; schema and migrations are future
work.
