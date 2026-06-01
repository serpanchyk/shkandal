# System Overview

Shkandal processes Ukrainian media and institutional articles through an
automatic dossier-building pipeline:

1. discover article URLs from a curated source list;
2. fetch pages and store raw HTML, extracted text, metadata, and remote image URLs;
3. classify relevance with a local binary ML classifier;
4. create a provisional Ukrainian article card with an LLM JSON contract;
5. retrieve candidate cases from Qdrant;
6. resolve article-case links and case relations with the LLM;
7. retrieve and resolve global entities from Qdrant;
8. retrieve and resolve global events from Qdrant;
9. materialize direct case-entity and case-event links;
10. update public case and entity pages immediately from PostgreSQL.

PostgreSQL is the source of truth. Qdrant has three rebuildable collections:
case cards, entity cards, and event cards.

Human review, user correction workflows, duplicate-case redirects, and advanced
analytics are later layers. The MVP publishes automatically after an initial
curated one-year backfill reaches a ready-enough checkpoint.

The current implementation is a foundation scaffold. It defines service
boundaries and runtime wiring but does not yet implement the article pipeline,
schema, classifier, prompts, or public dossier pages.
