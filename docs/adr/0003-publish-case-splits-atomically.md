# ADR 0003: Publish Case Splits Atomically

## Status

Accepted

## Decision

Case Coherence Audits prepare their full decision before acquiring the Case,
Entity, and Event mutation locks. A decisive audit then rewrites article
assignments, Case-scoped Entity/Event links, public copy, counts, and
vectors as one locked publication operation. PostgreSQL commits only after all
affected vectors are updated, so readers continue seeing the previous dossier
until the complete split is ready. Inconclusive or superseded audits make no
public mutation.

## Consequences

Case split throughput is intentionally serialized with all three identity
mutation namespaces. A PostgreSQL commit failure after Qdrant upserts can leave
orphan vectors, which remain harmless during PostgreSQL hydration and can be
removed by a rebuild.
