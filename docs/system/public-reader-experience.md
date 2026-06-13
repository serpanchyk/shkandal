# Public Reader Experience

The public reader experience is the implemented frontend/backend boundary that
turns the current PostgreSQL Case graph into Ukrainian-language dossier pages.
It reads live rows directly; the MVP has no publication snapshots or separate
content cache.

## Where It Lives

- `apps/frontend`: Next.js TypeScript public UI.
- `apps/backend`: FastAPI public API and page-composition queries.
- `packages/database`: source-of-truth models and public-reader migrations.
- `apps/backend/tests/seed_public_e2e.py`: deterministic public graph used by
  browser tests.

The frontend source routes are:

- `apps/frontend/src/app/page.tsx`: public Case feed.
- `apps/frontend/src/app/cases/[slug]/page.tsx`: Case dossier.
- `apps/frontend/src/app/entities/[slug]/page.tsx`: Entity page.
- `apps/frontend/src/app/sitemap.ts` and `robots.ts`: crawler surfaces.
- `apps/frontend/src/app/styles.css`: shared public visual system.

## Reader Surfaces

The homepage defaults to trending Cases and supports page-number navigation,
typo-tolerant title search, and five sort modes:

- `trending`: linked articles published during the previous seven days;
- `latest`: newest dated linked article;
- `newest`: Case creation time;
- `popular`: all-time anonymous aggregate Case views;
- `biggest`: linked article count.

Undated articles remain visible evidence but do not affect `trending` or
`latest`.

A public Case page contains:

- stable Ukrainian title and neutral summary;
- article, Event, and view metrics;
- compact `Джерела справи` Source-logo strip;
- oldest-to-newest Event timeline with expandable supporting articles;
- source-backed Mentioned Entities;
- Related Cases;
- newest-first linked article previews;
- an automatic-assembly disclaimer.

A public Entity page contains its canonical Ukrainian name, description,
aliases, Related Cases, and supporting articles that mention it. Public wording
uses `Mentioned Entity`; a source-backed mention does not assert guilt,
responsibility, or formal participation.

Article previews show source, date, title, and remote image when available.
They always link to the publisher's original article. Shkandal does not host
copied full article pages or proxy remote article images.

## Publication Rules

A Case is public only when it is active, has a non-empty Ukrainian summary, and
has at least one linked article.

An Entity page is public only when the Entity has a description, is linked to a
public Case, and has a supporting article. Source type is display context, not a
trust score; all supporting publisher types may appear under
`Джерела справи`.

Curated Source logo paths are nullable PostgreSQL metadata using the
`/sources/{source-slug}.png` convention. The corresponding logo files are
frontend-owned static assets under `apps/frontend/public/sources/`; missing
files fall back to Source initials in the reader UI.

## API Contract

The backend exposes strict Pydantic response contracts:

- `GET /api/cases?sort=trending&page=1&query=...`: feed, sorting, pagination,
  and optional fuzzy title search;
- `GET /api/events/latest`: up to 50 newest known-date Events linked to public
  Cases, ordered by occurrence date;
- `GET /api/cases/{slug}`: composed Case page;
- `POST /api/cases/{slug}/views`: anonymous aggregate view increment;
- `GET /api/entities/{slug}`: composed Entity page;
- `GET /api/sitemap`: public-ready Case and Entity routes;
- `GET /healthz`: backend health.

Search queries are 2 to 120 characters. PostgreSQL `pg_trgm` similarity ranks
fuzzy title matches. The backend reads current PostgreSQL rows and returns
page-ready data so public composition rules remain outside the frontend.

Case views are intentionally approximate. The frontend stores
`shkandal:viewed:{slug}` in browser session storage and sends at most one view
increment per Case per browser session. The backend stores only an anonymous
aggregate count.

## Runtime Boundary

Compose publishes the frontend at <http://localhost:3000> and the backend at
<http://localhost:8000>. It gives the frontend two backend URLs:

- `BACKEND_INTERNAL_URL=http://backend:8000` for server-side rendering inside
  Compose;
- `NEXT_PUBLIC_BACKEND_URL=http://localhost:8000` for browser-side view
  counting.

`NEXT_PUBLIC_SITE_URL` supplies the public origin for metadata and sitemap
generation. `PUBLIC_FRONTEND_ORIGIN` limits backend CORS to the public frontend
origin.

## Visual Direction

The implemented interface is a light-gray technical dossier design with
restrained blue-purple grain gradients, dark outlined containers, monospace
identity typography, and readable sans-serif body copy. The feed, Case pages,
Entity pages, loading state, error state, and not-found state share this visual
system.

## Verification

Backend tests cover publication filtering, sorting, fuzzy search, Case and
Entity composition, sitemap entries, and view counting. Worker tests protect
public metrics: retrying an Article/Case link cannot inflate article count,
undated articles cannot create a fictional latest date, older articles cannot
lower the latest date, and copy regeneration cannot bump the Case update time.

Playwright covers the seeded reader journey through the feed, Case timeline
provenance, original-source links, Entity pages, and disclaimer. CI starts an
isolated PostgreSQL service, runs migrations, seeds a deterministic graph,
starts the backend, and executes the browser tests.

Local Playwright execution must use an isolated disposable database because the
seed script writes a deterministic graph.
