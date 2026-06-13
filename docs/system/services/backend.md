# Backend

The backend is a FastAPI service. It owns public API boundaries and application
business logic that should not live in workers or the frontend.

Public API areas:

- sortable case feed for latest, newest, popular, biggest, and trending views;
- case page data with title, summary, entities, chronological events, source articles, and disclaimer text;
- entity page data with description, aliases, related cases, and mentioned articles;
- anonymous aggregate case view counting;
- source/article preview data that links users to the original source URL.

The feed defaults to `trending`. `latest` uses the newest linked article
publication time; `trending` counts linked articles published in the previous
seven days; `popular` uses all-time aggregate views; `biggest` uses linked
article count; and `newest` uses Case creation time. Undated articles do not
affect `latest` or `trending`. Each Case feed card uses the image from the first
article linked to the Case that has a reachable, non-empty remote image URL.
Before returning a feed page, the backend checks ordered image candidates with
short streaming HTTP requests and skips 4xx/5xx responses and transport
failures. Checks run concurrently across Cases and try at most
`image_check_max_candidates` URLs per Case, each with
`image_check_timeout_seconds`. Results are cached in backend memory for
`image_check_cache_ttl_seconds` to avoid checking the same publisher URL on
every feed request.

Only active Cases with a non-empty Ukrainian summary and at least one linked
article are public. Only described Entities linked to a public Case and a
supporting article are public. Fuzzy Case-title search uses PostgreSQL trigram
similarity and relevance ordering.

The API reads current PostgreSQL rows directly in the MVP. There are no
published snapshots. Multi-row public-page updates should be transactional where
possible so readers do not see event data without provenance.

Case-feed requests therefore have a bounded runtime dependency on publisher
image hosts. The backend does not proxy or cache image bytes; it only verifies
that a candidate currently responds before returning its remote URL.

Current endpoints:

- `GET /healthz`: returns service status.
- `GET /metrics`: Prometheus request/process metrics and read-only durable
  pipeline aggregates.
- `GET /api/cases`: paginated feed and fuzzy Case-title search.
- `GET /api/cases/{slug}`: composed public Case page.
- `POST /api/cases/{slug}/views`: anonymous aggregate view increment.
- `GET /api/entities/{slug}`: composed public Entity page.
- `GET /api/sitemap`: public-ready Case and Entity routes.

Request metrics use FastAPI route templates rather than raw URLs. Pipeline
metrics expose aggregate job state, recent LLM run statuses, and shared durable
LLM cooldown state without article, Case, URL, or error-message labels.

See [Public Reader Experience](../public-reader-experience.md) for the complete
frontend/backend reader contract, publication rules, runtime boundary, and
verification approach.
