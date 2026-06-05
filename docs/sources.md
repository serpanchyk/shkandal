# Source Inventory

This inventory describes the curated ingestion source catalog implemented in
`worker_ingestion.sources`. It is not a live validation report. Run
`uv run python apps/worker-ingestion/scripts/validate_sources.py --sample 2` to
check current robots, discovery endpoints, and extraction quality.

Extraction is generic-first through `trafilatura`; configured CSS
`body_selectors` are fallback-only selectors when generic extraction is missing
or too short.

## Backfill Run Notes

### 2026-06-03 12-month ingestion observation

Started the current `worker-ingestion` Docker image for an all-source backfill
covering `2025-06-03T00:00:00+00:00` through
`2026-06-03T23:59:59+00:00`.

Command:

```bash
docker compose run -d --name shkandal-ingestion-backfill-20260603-12mo worker-ingestion python -m worker_ingestion.main --since 2025-06-03T00:00:00+00:00 --until 2026-06-03T23:59:59+00:00
```

Five-minute observation result:

| Source | Observed status |
| --- | --- |
| `pravda` | Completed first. Discovered 20 feed URLs, stored 19 HTML articles, and recorded 1 fetch failure for `https://www.pravda.com.ua/news/2026/06/03/8037513/` with HTTP 403. |
| `hromadske` | Started second. Discovery hit the date-bounded cap of 10,000 URLs. After the five-minute check the container was still running in this source; article fetches were progressing but several transport failures were logged. |

Database snapshot after the observation window:

| Source | Rows fetched in this run | Rows with raw HTML | Failure records |
| --- | ---: | ---: | ---: |
| `pravda` | 20 | 19 | 1 |
| `hromadske` | 4,145 | 4,133 | 12 |

The backfill container was left running after the observation window. The main
early risk is `hromadske` throughput/reliability: logged failures included
`non_2xx_response` with status `0` and `All connection attempts failed`.

### 2026-06-05 article coverage audit

Checked the local PostgreSQL database while the normal Compose stack was
running. The audit window matches the 12-month backfill note:
`2025-06-03T00:00:00+00:00` through `2026-06-03T23:59:59+00:00`.

Read-only checks used:

```bash
DOCKER_CONTEXT=default docker compose ps
DOCKER_CONTEXT=default docker compose exec -T postgres psql -U shkandal -d shkandal -c "<coverage aggregate>"
```

`apps/worker-ingestion/scripts/article_coverage_report.py` was attempted with a
local `POSTGRES_DATABASE_URL`, but it did not produce output within the wait
window. The SQL aggregates below are the verified source of this snapshot.

Coverage summary:

| Source | Stored rows in window | Undated rows | Dated coverage | Coverage finding |
| --- | ---: | ---: | --- | --- |
| `pravda` | 36,066 | 1,235 | 2025-06-03 to 2026-06-03 | Good dated coverage; 1,230 rows have missing `raw_html`. |
| `tyzhden` | 1,453 | 0 | 2025-06-03 to 2026-06-03 | Good dated coverage. |
| `antac` | 228 | 71 | 2025-06-09 to 2026-06-03 | Good dated coverage after a six-day start gap; 50 rows have missing `raw_html`. |
| `bihus` | 106 | 0 | 2025-06-09 to 2026-06-01 | Good dated coverage after a six-day start gap. |
| `hromadske` | 10,053 | 12 | 2025-07-31 to 2026-06-03 | Missing dated months: 2025-06, 2025-10, 2025-11, 2025-12. |
| `slovoidilo` | 10,320 | 842 | 2025-08-01 to 2026-06-03 | Missing dated months: 2025-06, 2025-07, 2025-10, 2025-11, 2025-12. |
| `suspilne` | 8,197 | 6 | 2025-12-03 to 2026-06-03 | Missing dated months: 2025-06 through 2025-11. |
| `espreso` | 5,424 | 566 | 2026-03-10 to 2026-06-03 | Missing dated months: 2025-06 through 2026-02. |
| `radiosvoboda` | 1,586 | 0 | 2026-03-15 to 2026-06-03 | Missing dated months: 2025-06 through 2026-02 and 2026-05. |
| `babel` | 182 | 0 | 2026-05-27 to 2026-06-03 | Severely underingested before late May 2026. |
| `ccu` | 15 | 11 | 2025-12-31 to 2026-06-02 | Mostly undated; only December 2025 and June 2026 have dated rows. |
| `chesno` | 581 | 578 | 2026-06-02 to 2026-06-03 | Mostly undated; date extraction must be fixed before coverage can be trusted. |
| `court-gov` | 40 | 22 | 2026-06-02 to 2026-06-03 | Mostly recent/undated; 4 rows have missing `raw_html`. |
| `gp` | 24 | 10 | 2026-06-02 to 2026-06-03 | Mostly recent/undated; historical backfill missing. |
| `hcac` | 36 | 32 | 2026-06-02 to 2026-06-03 | Mostly undated; 1 row has missing `raw_html`. |
| `nashigroshi` | 726 | 721 | 2026-06-02 to 2026-06-03 | Mostly undated; date extraction must be fixed before coverage can be trusted. |
| `nazk` | 16 | 14 | 2026-06-02 to 2026-06-03 | Mostly undated/recent only. |
| `rada` | 34 | 30 | 2026-06-03 only | Mostly undated/recent only. |
| `rnbo` | 13 | 11 | 2026-06-02 only | Mostly undated/recent only. |
| `supreme-court` | 26 | 17 | 2026-06-02 to 2026-06-03 | Mostly undated/recent only. |
| `arma` | 10 | 10 | none | Stored rows are all undated. |
| `npu` | 10 | 10 | none | Stored rows are all undated. |
| `texty` | 560 | 560 | none | Stored rows are all undated; coverage by month is currently unusable. |
| `dbr` | 0 | 0 | none | Not ingested in the window. Prior TLS-chain blocker in this runtime; now routed through browser impersonation for validation. |
| `kmu` | 0 | 0 | none | Not ingested in the window. Prior Radware captcha blocker; now routed through browser impersonation for validation. |
| `nabu` | 0 | 0 | none | Not ingested in the window. Prior HTTP 403 blocker; now routed through browser impersonation for validation. |
| `president` | 0 | 0 | none | Not ingested in the window. Prior Akamai HTTP 403 blocker; now routed through browser impersonation for validation. |
| `ssu` | 0 | 0 | none | Not ingested in the window. Prior Akamai HTTP 403 blocker; now routed through browser impersonation for validation. |

Under-ingestion priorities:

1. Previously blocked official sources with zero articles: `nabu`, `dbr`,
   `ssu`, `kmu`, and `president`. These now use browser-impersonated requests
   and need live validation before normal backfill can be trusted.
2. Sources storing only or mostly undated rows: `texty`, `nashigroshi`,
   `chesno`, `arma`, `npu`, `hcac`, `rada`, `rnbo`, `nazk`, `ccu`,
   `court-gov`, `supreme-court`, and `gp`. For these, fix published-date
   extraction first; otherwise article counts exist but historical coverage
   cannot be proven.
3. Dated media backfill gaps: `babel`, `radiosvoboda`, `espreso`, `suspilne`,
   `slovoidilo`, and `hromadske` have clear missing months in the expected
   window. These likely need sitemap pagination/monthly sitemap coverage
   checks after date extraction issues are separated out.
4. Raw HTML gaps worth repair: `pravda` has 1,230 rows without `raw_html`,
   `antac` has 50, `hromadske` has 12, `suspilne` has 6, `court-gov` has 4,
   and `hcac` has 1.

### 2026-06-05 browser impersonation validation

After extending the browser-impersonated transport beyond `pravda`, read-only
validation was run with one sample article per affected source:

```bash
uv run python apps/worker-ingestion/scripts/validate_sources.py --source <source> --sample 1 --timeout 8
```

Results:

| Source | Validation result |
| --- | --- |
| `nabu` | Section fetch returned 200 and one discovered article extracted successfully with title, `published_at`, and 1,263 characters of text. `robots.txt` returned 404, which is not treated as an ingestion blocker when article discovery works. |
| `ssu` | Section fetch returned 200 and one discovered article extracted successfully with title, `published_at`, and 1,542 characters of text. `robots.txt` returned 404, which is not treated as an ingestion blocker when article discovery works. |
| `president` | `robots.txt`, section fetch, discovery, and one article extraction all succeeded. The sample article had title, `published_at`, and 2,160 characters of text. |
| `kmu` | `robots.txt` and timeline fetch returned 200, but no article URLs were discovered. This is no longer a raw request blocker; it needs a KMU-specific discovery/parser fix. |
| `dbr` | Still blocked by `SSL certificate problem: unable to get local issuer certificate`; browser impersonation does not fix the incomplete certificate chain. |

## Supported Sources

| Source | Type | Robots | RSS | Sitemap | Section URL | Include / exclude summary | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `pravda` | media | Manual validation required | `https://www.pravda.com.ua/rss/view_news/` | `https://www.pravda.com.ua/sitemap/sitemap.xml` | Not configured | Include `/news/`; exclude Russian/English paths | Existing media source. |
| `hromadske` | media | Manual validation required | Not configured | `https://hromadske.ua/sitemap.xml` | Not configured | Exclude `/ru/`, `/en/` | Existing media source. |
| `radiosvoboda` | media | Manual validation required | `https://www.radiosvoboda.org/rss/` | `https://www.radiosvoboda.org/sitemap.xml` | Not configured | Uses sitemap filters | Existing media source. |
| `suspilne` | media | Manual validation required | Not configured | `https://suspilne.media/sitemap.xml` | Not configured | Uses sitemap filters | Existing media source. |
| `bihus` | media | Manual validation required | `https://bihus.info/feed/` | `https://bihus.info/sitemap.xml` | Not configured | Uses sitemap filters | Existing media source. |
| `antac` | media | Manual validation required | `https://antac.org.ua/feed/` | `https://antac.org.ua/sitemap.xml` | Not configured | Uses sitemap filters | Existing media source. |
| `nashigroshi` | media | Manual validation required | `https://nashigroshi.org/feed/` | `https://nashigroshi.org/sitemap.xml` | Not configured | Uses sitemap filters | Existing media source. |
| `babel` | media | Manual validation required | `https://babel.ua/rss.xml` | `https://babel.ua/sitemap.xml` | Not configured | Uses Ukrainian sitemap filters | Existing media source. |
| `texty` | media | Manual validation required | `https://texty.org.ua/feed.xml` | `https://texty.org.ua/sitemap.xml` | Not configured | Include `/articles/`; uses sitemap filters | Existing media source. |
| `espreso` | media | Manual validation required | `https://espreso.tv/rss` | `https://espreso.tv/sitemap.xml` | Not configured | Uses news sitemap filters | Existing media source. |
| `slovoidilo` | media | Manual validation required | Not configured | `https://www.slovoidilo.ua/sitemap_index_uk.xml`, `https://www.slovoidilo.ua/news_sitemap_uk.xml` | Not configured | Uses Ukrainian monthly sitemap filters | Existing media source. |
| `tyzhden` | media | Manual validation required | `https://tyzhden.ua/feed/` | `https://tyzhden.ua/wp-sitemap.xml` | Not configured | Uses post sitemap filters | Existing media source. |
| `chesno` | media | Manual validation required | Not configured | `https://www.chesno.org/sitemap.xml` | Not configured | Uses post sitemap filters | Existing media source. |
| `nabu` | law enforcement | Manual validation required | Not configured | Not configured | `https://nabu.gov.ua/news/` | Include `/news/<slug>/`; exclude English, search, archives, orders, summonses, wanted notices, document files | Official news section only. |
| `hcac` | court | Manual validation required | Not configured | Not configured | `https://hcac.court.gov.ua/hcac/pres-centr/news/`, `https://hcac.court.gov.ua/hcac/info_sud/news` | Include official news IDs under those paths | Court portal news sections only. |
| `dbr` | law enforcement | Manual validation required | Not configured | Not configured | `https://dbr.gov.ua/news` | Include `/news/<slug>`; exclude assets, admin, search, documents, images | Official news only. |
| `nazk` | institution | Manual validation required | Not configured | Not configured | `https://nazk.gov.ua/uk/novyny/` | Include `/uk/novyny/<slug>/`; exclude declarations, dashboards, documents, uploads | Registry and document areas are excluded. |
| `arma` | institution | Manual validation required | Not configured | Not configured | `https://arma.gov.ua/news` | Include `/news/typical/<slug>`; exclude document files | Official news path only. |
| `gp` | law enforcement | Manual validation required | Not configured | Not configured | `https://gp.gov.ua/ua/categories/novini` | Include `/ua/posts/<slug>`; exclude regional subdomains, documents, search, files | Official post paths only; needs live validation. |
| `ssu` | law enforcement | Manual validation required | Not configured | Not configured | `https://ssu.gov.ua/novyny` | Include `/novyny/<slug>`; exclude English, galleries, search | Official news path only. |
| `npu` | law enforcement | Manual validation required | Not configured | Not configured | `https://npu.gov.ua/api/timeline?type=posts&category_id=35&page=1` | Include `/news/<slug>`; exclude search, static files, documents | Official news timeline is JSON/API-backed. |
| `court-gov` | court | Manual validation required | Not configured | Not configured | `https://court.gov.ua/press/news/` | Include `/press/news/<id>`; exclude decision databases, schedules, search, storage | Avoids registry and schedule crawling. |
| `supreme-court` | court | Manual validation required | Not configured | Not configured | `https://supreme.court.gov.ua/supreme/pres-centr/news/` | Include `/supreme/pres-centr/news/<id>` | Official Supreme Court news section. |
| `ccu` | court | Manual validation required | `https://ccu.gov.ua/rss.xml` | Not configured | `https://ccu.gov.ua/storinka/novyny` | Include `/novyna/<slug>` and validated news publication paths; exclude decisions, document libraries, files | Canonical news paths need live validation. |
| `rada` | parliament | Manual validation required | `https://www.rada.gov.ua/rss/` | Not configured | `https://www.rada.gov.ua/news/Novyny/`, `https://www.rada.gov.ua/news/news_kom/` | Include `.html` news items; exclude law databases, bill cards, uploads, files, search | Avoids `zakon.rada.gov.ua` and bill registry crawling. |
| `kmu` | government | Manual validation required | Not configured | Not configured | `https://www.kmu.gov.ua/timeline?&type=posts` | Include `/news/<slug>`; exclude `/npas`, petitions, storage, search | Official post timeline only. |
| `president` | government | Manual validation required | Not configured | Not configured | `https://www.president.gov.ua/news` | Include `/news/<slug>-<id>`; exclude documents, petitions, photo/video galleries | Text news only. |
| `rnbo` | government | Manual validation required | Not configured | Not configured | `https://www.rnbo.gov.ua/ua/Diialnist/` | Include `/ua/Diialnist/<id>.html`; exclude files and documents | Activity/news-like pages only. |

## Problematic Or Unsupported Sources

| Source | Status | Reason |
| --- | --- | --- |
| `sap.gov.ua` | Manual review required | Prior probing timed out and search results primarily exposed Telegram/social mirrors. Do not add until an official RSS, sitemap, or news section is verified. |
| `itd.rada.gov.ua` | Unsupported | Appears to be an electronic cabinet / bill-information system, not a news source. Excluded to avoid bill and registry crawling. |
