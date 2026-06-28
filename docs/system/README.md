# System Overview

Shkandal processes Ukrainian media and institutional articles through an
automatic dossier-building pipeline:

1. discover article URLs from a curated source list;
2. fetch pages and store raw HTML, extracted text, metadata, and remote image URLs;
3. classify relevance with a local binary ML classifier;
4. create a provisional Ukrainian article card with an LLM JSON contract;
5. retrieve candidate cases from Qdrant;
6. resolve article-case links with the LLM;
7. retrieve and resolve global entities from Qdrant;
8. retrieve and resolve global events from Qdrant;
9. materialize direct case-entity and case-event links;
10. refresh Case title/summary when missing, on square evidence thresholds, or after repairs;
11. update public case and entity pages from PostgreSQL;
12. periodically audit Case coherence and atomically split mixed durable stories;
13. derive Other Cases navigation from shared evidence.

One relevant article is enough to create a case, and one supporting article is
enough to create an event. Source provenance must remain visible. Articles can
also belong to cases without producing extracted timeline events.

PostgreSQL is the source of truth. Qdrant has three rebuildable collections:
case cards, entity cards, and event cards.

Human review, user correction workflows, duplicate-case redirects, and advanced
analytics are later layers. The MVP publishes automatically after an initial
curated one-year backfill reaches a ready-enough checkpoint.

The current implementation includes ingestion, classifier and LLM-resolution
workflows, the PostgreSQL evidence graph, a public FastAPI query boundary, and
server-rendered public feed, Case, and Entity pages. Qdrant-backed candidate
retrieval remains planned work.

Foundation notes:

- [Configuration](foundation/configuration.md)
- [Database](foundation/database.md)
- [Logging](foundation/logging.md)
- [Observability](foundation/observability.md)
- [Runtime](foundation/runtime.md)
- [Scheduling](foundation/scheduling.md)
- [Testing and CI](foundation/testing-ci.md)
- [Public Reader Experience](public-reader-experience.md)
