# Runtime

Docker Compose is the default runtime boundary.

Runtime dependencies:

- PostgreSQL 16 for durable application data.
- Qdrant for rebuildable case, entity, and event vector indexes.

Redis is intentionally excluded from the MVP. Background work can start with a
single generic PostgreSQL jobs table and row locking.

The first public launch should happen after a curated one-year backfill reaches
a ready-enough checkpoint. After launch, pages update automatically from current
database rows.
