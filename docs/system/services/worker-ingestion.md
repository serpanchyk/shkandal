# Worker Ingestion

The ingestion worker owns source discovery, page fetching, extraction, URL
identity, and article persistence.

Current implemented scope is curated media and institutional source ingestion.
Institutional sources use conservative URL patterns to avoid registry,
document, search, and archive crawling.

Implemented responsibilities:

- read a curated source list from `worker_ingestion.sources`;
- discover URLs from `sitemap.xml`, sitemap indexes, nested sitemaps,
  gzipped sitemap files, RSS/Atom feeds, and configured section pages;
- use a higher per-source discovery cap for date-bounded backfills and skip
  clearly out-of-window year/month archive sitemaps;
- apply source include/exclude URL patterns before fetching article pages;
- skip already-stored discovered article identities before page fetching, using
  one indexed database lookup per source pass;
- fetch pages asynchronously with configured timeout, concurrency, and
  user-agent;
- extract title, lead, author, publication date, source language, extracted
  text, remote image URL, raw HTML, and source metadata;
- repair missing publication dates from stored raw HTML without refetching;
- use `trafilatura` as the generic-first text extractor, with CSS selectors as
  fallback only when generic extraction is missing or too short;
- normalize article identity URLs and upsert by `articles.identity_url`;
- keep the raw discovered URL unchanged in `articles.url`;
- persist failed article fetch attempts with fetch metadata when the article
  URL can be identified;
- emit structured progress logs for worker start/finish, each source start,
  source discovery counts, skipped existing article counts, source finish
  counts, and failed article fetches.
- provide a read-only article coverage report grouped by source and calendar
  period for finding sources with no articles and skipped ingestion periods.

Configured source groups:

- media: `pravda`, `hromadske`, `radiosvoboda`, `suspilne`, `bihus`,
  `antac`, `nashigroshi`, `babel`, `texty`, `espreso`, `slovoidilo`,
  `tyzhden`, `chesno`;
- law enforcement: `nabu`, `dbr`, `gp`, `ssu`, `npu`;
- courts: `hcac`, `court-gov`, `supreme-court`, `ccu`;
- institutions: `nazk`, `arma`;
- parliament: `rada`;
- government: `kmu`, `president`, `rnbo`.

See `docs/sources.md` for endpoint patterns, manual-review notes, and
unsupported sources.

## URL Identity

`articles.url` stores the raw URL discovered from a sitemap, feed, or section
page. It is not used as the duplicate key.

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

Before fetching article pages, the worker also normalizes discovered URLs and
checks which identities already exist in `articles.identity_url`. Exact matches
are skipped before fetch and extraction. Canonical-only duplicates that can only
be known after reading article HTML still fall back to the database upsert path.

## Publication Dates

Article `published_at` is extracted from article HTML, not from sitemap
`lastmod`. The extractor checks common Open Graph/article metadata, JSON-LD
`datePublished`, schema.org `itemprop` fields, `<time>` `content`/`datetime`
attributes, and trafilatura metadata. Naive publisher timestamps are treated as
Europe/Kyiv time and stored as UTC datetimes.

## Running

Run all configured sources through Docker Compose:

```bash
docker compose run --rm worker-ingestion
```

The worker is currently a one-shot process. It runs one ingestion pass and then
exits; use `docker compose run --rm worker-ingestion` for a visible foreground
run, or inspect named one-off containers with `docker logs <container>` when a
manual backfill was started with a fixed container name.

Run one source for debugging:

```bash
docker compose run --rm worker-ingestion python -m worker_ingestion.main --source pravda --limit 20
```

Optional date window arguments use ISO datetime/date strings accepted by
`datetime.fromisoformat`:

```bash
docker compose run --rm worker-ingestion python -m worker_ingestion.main --source hromadske --since 2026-06-01 --until 2026-06-02
```

Date-bounded runs use `max_backfill_urls_per_source` as the effective discovery
cap when it is higher than `max_sitemap_urls_per_source`. The default backfill
cap is 10,000 discovered article URLs per source.
Date-only `--until` values are treated as the end of that calendar day. Dense
sources can override the date-bounded discovery cap with
`--max-backfill-urls-per-source`.
When a date-bounded run fetches a candidate whose discovery metadata did not
include a usable date, the worker checks the extracted article `published_at`
before storage and skips articles outside the requested window.
Pravda uses a browser-impersonated fetch path for all requests from Docker,
because Cloudflare challenges the default Python HTTP client on sitemap and
some article URLs. It also uses a source-level crawl delay and single in-flight
fetch to avoid 429 rate limits.

Repair missing publication dates from already-stored raw HTML without refetching
articles. Repair mode is a dry run unless `--apply` is passed:

```bash
docker compose run --rm worker-ingestion python -m worker_ingestion.main --repair-missing-published-at --source espreso --limit 1000
docker compose run --rm worker-ingestion python -m worker_ingestion.main --repair-missing-published-at --source espreso --limit 1000 --apply
```

Source type is stored as context and UI metadata, not as an authority score.
Supported source types include media, institution, court, NGO, government,
parliament, law enforcement, and other.

Run read-only source validation:

```bash
uv run python apps/worker-ingestion/scripts/validate_sources.py --sample 2
```
