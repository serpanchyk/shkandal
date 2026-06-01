# Worker Ingestion

The ingestion worker owns source discovery, page fetching, extraction, URL
identity, and article persistence.

Current implemented scope is media-only sitemap ingestion. Institution and
official sources remain planned but are not configured in this slice.

Implemented responsibilities:

- read a curated media source list from `worker_ingestion.sources`;
- discover URLs from `sitemap.xml`, sitemap indexes, nested sitemaps, and
  gzipped sitemap files;
- apply source include/exclude URL patterns before fetching article pages;
- fetch pages asynchronously with configured timeout, concurrency, and
  user-agent;
- extract title, lead, author, publication date, source language, extracted
  text, remote image URL, raw HTML, and source metadata;
- normalize article identity URLs and upsert by `articles.identity_url`;
- keep the raw discovered URL unchanged in `articles.url`;
- persist failed article fetch attempts with fetch metadata when the article
  URL can be identified.

Configured media sources:

- `pravda`
- `hromadske`
- `radiosvoboda`
- `suspilne`
- `bihus`
- `antac`
- `nashigroshi`
- `babel`
- `texty`
- `espreso`
- `slovoidilo`
- `tyzhden`
- `chesno`

## URL Identity

`articles.url` stores the raw URL discovered from the sitemap. It is not used as
the duplicate key.

`articles.identity_url` stores the canonical identity used for deduplication.
The normalizer:

- lowercases host names;
- removes a leading `www.`;
- normalizes `http` and `https` to `https`;
- removes URL fragments;
- removes common tracking query parameters;
- preserves unknown query parameters;
- normalizes duplicate path slashes and trailing slash variants.

When an article page has `<link rel="canonical" href="...">`, the worker uses
that value after normalization. Otherwise it normalizes the raw discovered URL.
The database uniqueness constraint on `articles.identity_url` remains the final
duplicate authority, and upserts avoid replacing existing non-empty data with
empty extraction results.

## Running

Run all configured media sources through Docker Compose:

```bash
docker compose run --rm worker-ingestion
```

Run one source for debugging:

```bash
docker compose run --rm worker-ingestion python -m worker_ingestion.main --source pravda --limit 20
```

Optional date window arguments use ISO datetime/date strings accepted by
`datetime.fromisoformat`:

```bash
docker compose run --rm worker-ingestion python -m worker_ingestion.main --source hromadske --since 2026-06-01 --until 2026-06-02
```

Source type is stored as context and UI metadata, not as an authority score.
Expected future source types include media, institution, court, NGO, and other.
