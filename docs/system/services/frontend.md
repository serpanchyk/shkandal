# Frontend

The frontend is a Next.js TypeScript app for the public Ukrainian reader
experience.

Implemented MVP surfaces:

- active homepage case feed;
- sorting modes for latest, newest, popular, biggest, and trending cases;
- case pages with stable title, neutral summary, entities, chronological events, article source popups, and linked-articles section;
- entity pages with description, aliases, related cases, and mentioned articles;
- a static `Про Шкандаль` page explaining the product purpose, automatic
  assembly process, reading limits, and development support;
- article preview cards with source name, date, title, remote image URL when available, and a direct link to the original source;
- short visible disclaimer that pages are automatically assembled from open sources.

The frontend server-renders current API data without page-data caching. The
homepage defaults to trending Cases, supports five sort modes, page-number
navigation, header-based fuzzy Case-title search, a featured first-page layout
with one lead Case and four supporting Cases, a compact one-row-per-Case feed,
and an animated rolling list of the newest known-date Events. Search results and
later feed pages use only the compact list. Case pages show a compact
`Джерела справи` Source-logo strip, oldest-to-newest timeline with inline
expandable provenance, source-backed mentioned Entities, related Cases, and
newest-first linked articles.

Every route ends with a global trust footer that briefly explains automatic
dossier assembly, links to `Про Шкандаль` and the project repository, and
credits the organizations that supported development.

The visual system uses a light-gray technical dossier interface with restrained
blue-purple grain gradients, a visible grain texture, dark outlined containers, monospace identity
typography, and readable sans-serif body copy. Case views are counted once per
browser session through session storage. Generated database slugs stay in
stable routes but are not shown as reader-facing labels.

Frontend source lives under `apps/frontend`. See
[Public Reader Experience](../public-reader-experience.md) for routes, runtime
URLs, reader behavior, API integration, and verification.

The production Compose deployment builds the frontend with
`NEXT_PUBLIC_SITE_URL` as the browser-visible origin and mirrors that value
into `NEXT_PUBLIC_BACKEND_URL` so browser-side API calls continue to flow
through Caddy instead of bypassing the public edge.
