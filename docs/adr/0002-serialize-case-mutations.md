# ADR 0002: Serialize Case Mutations

## Status

Accepted

## Context

Concurrent article resolvers can retrieve before another newly created Case is
visible in Qdrant and create duplicate dossiers. PostgreSQL is authoritative,
while Qdrant is a separate rebuildable retrieval index without shared
transactions.

## Decision

Article-case resolution and case-copy updates share one PostgreSQL advisory
lock. An unavailable lock defers the job without consuming an attempt. The
worker hydrates retrieved candidates from PostgreSQL and upserts affected Case
vectors before committing PostgreSQL Case mutations. A Qdrant failure rolls
back the PostgreSQL transaction.

## Consequences

Case mutation throughput is intentionally serialized. Retrieval sees each
committed Case mutation before the next resolver runs. A PostgreSQL commit
failure after Qdrant upsert can leave an orphan point, which is ignored during
PostgreSQL hydration and removed by a rebuild.
