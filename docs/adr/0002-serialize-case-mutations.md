# ADR 0002: Serialize Global Identity Mutations

## Status

Accepted

## Context

Concurrent article resolvers can retrieve before a newly created Case, Entity,
or Event is visible in Qdrant and create duplicate global identities. PostgreSQL
is authoritative, while Qdrant is a separate rebuildable retrieval index
without shared transactions.

## Decision

Article-case resolution and case-copy updates share one PostgreSQL advisory
lock. An unavailable lock defers the job without consuming an attempt. The
worker hydrates retrieved candidates from PostgreSQL and upserts affected Case
vectors before committing PostgreSQL Case mutations. A Qdrant failure rolls
back the PostgreSQL transaction.

Entity and Event mutations use separate advisory locks for their respective
identity namespaces. Those stages may run concurrently with each other, but
mutations within one namespace are serialized. Their candidates are likewise
hydrated from PostgreSQL and affected vectors are upserted before commit.

## Consequences

Mutation throughput is intentionally serialized per identity namespace.
Retrieval sees each committed mutation before the next resolver in that
namespace runs. A PostgreSQL commit failure after Qdrant upsert can leave an
orphan point, which is ignored during PostgreSQL hydration and removed by a
rebuild.
