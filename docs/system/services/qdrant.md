# Qdrant

Qdrant stores rebuildable vector indexes used by `worker-ml`.

Planned MVP collections:

- case cards;
- entity cards;
- event cards.

The article card is embedded to retrieve candidate cases. Provisional entity
cards retrieve candidate global entities. Provisional event cards retrieve
candidate global events.

Qdrant is always derived from PostgreSQL-backed data and must not become the
source of truth.
