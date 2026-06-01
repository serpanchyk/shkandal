# Backend

The backend is a FastAPI service. It owns public API boundaries and application
business logic that should not live in workers or the frontend.

Planned public API areas:

- sortable case feed for latest, newest, popular, biggest, and trending views;
- case page data with title, summary, entities, chronological events, source articles, and disclaimer text;
- entity page data with description, aliases, related cases, and mentioned articles;
- anonymous aggregate case view counting;
- source/article preview data that links users to the original source URL.

The API reads current PostgreSQL rows directly in the MVP. There are no
published snapshots. Multi-row public-page updates should be transactional where
possible so readers do not see event data without provenance.

Current endpoint:

- `GET /healthz`: returns service status.
