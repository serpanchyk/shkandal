# Runtime

Docker Compose is the default runtime boundary.

Runtime dependencies:

- PostgreSQL 16 for durable application data.
- Qdrant for vector indexes.

Redis is intentionally excluded from the MVP. Background work can start with a
PostgreSQL jobs table and row locking.
