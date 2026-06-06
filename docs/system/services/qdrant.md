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
remain service-level responsibilities. `worker-ml` currently implements the
embedding service and vector-index integration using
`intfloat/multilingual-e5-small`, which produces 384-dimensional vectors. The
shared vector-store default is therefore 384 dimensions with cosine distance.

Existing local Qdrant collections created with an older vector size must be
rebuilt manually before indexing E5 vectors. The bootstrap helper intentionally
does not delete or recreate existing collections.
