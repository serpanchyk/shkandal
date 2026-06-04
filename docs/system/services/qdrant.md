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

## Shared Package

`packages/vector_store` owns the shared thin Qdrant integration layer:

- `VectorStoreConfig` defines the Qdrant URL, collection names, vector size, and
  distance metric;
- `create_qdrant_client` creates an async Qdrant client;
- `bootstrap_qdrant_collections` creates missing case, entity, and event
  collections without deleting or recreating existing collections;
- `CaseVectorRepository`, `EntityVectorRepository`, and `EventVectorRepository`
  expose typed upsert, delete, and search operations for caller-supplied vectors.

Embedding generation, PostgreSQL rebuild orchestration, and LLM resolution
remain service-level responsibilities, currently planned for `worker-ml`.
