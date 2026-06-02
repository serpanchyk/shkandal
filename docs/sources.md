# Source Inventory

This inventory describes the curated ingestion source catalog implemented in
`worker_ingestion.sources`. It is not a live validation report. Run
`uv run python apps/worker-ingestion/scripts/validate_sources.py --sample 2` to
check current robots, discovery endpoints, and extraction quality.

Extraction is generic-first through `trafilatura`; configured CSS
`body_selectors` are fallback-only selectors when generic extraction is missing
or too short.

## Supported Sources

| Source | Type | Robots | RSS | Sitemap | Section URL | Include / exclude summary | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `pravda` | media | Manual validation required | Not configured | `https://www.pravda.com.ua/sitemap/sitemap.xml` | Not configured | Include `/news/`; exclude Russian/English paths | Existing media source. |
| `hromadske` | media | Manual validation required | Not configured | `https://hromadske.ua/sitemap.xml` | Not configured | Exclude `/ru/`, `/en/` | Existing media source. |
| `radiosvoboda` | media | Manual validation required | Not configured | `https://www.radiosvoboda.org/sitemap.xml` | Not configured | Uses sitemap filters | Existing media source. |
| `suspilne` | media | Manual validation required | Not configured | `https://suspilne.media/sitemap.xml` | Not configured | Uses sitemap filters | Existing media source. |
| `bihus` | media | Manual validation required | Not configured | `https://bihus.info/sitemap.xml` | Not configured | Uses sitemap filters | Existing media source. |
| `antac` | media | Manual validation required | Not configured | `https://antac.org.ua/sitemap.xml` | Not configured | Uses sitemap filters | Existing media source. |
| `nashigroshi` | media | Manual validation required | Not configured | `https://nashigroshi.org/sitemap.xml` | Not configured | Uses sitemap filters | Existing media source. |
| `babel` | media | Manual validation required | Not configured | `https://babel.ua/sitemap.xml` | Not configured | Uses Ukrainian sitemap filters | Existing media source. |
| `texty` | media | Manual validation required | Not configured | `https://texty.org.ua/sitemap.xml` | Not configured | Uses sitemap filters | Existing media source. |
| `espreso` | media | Manual validation required | Not configured | `https://espreso.tv/sitemap.xml` | Not configured | Uses news sitemap filters | Existing media source. |
| `slovoidilo` | media | Manual validation required | Not configured | `https://www.slovoidilo.ua/sitemap_index_uk.xml`, `https://www.slovoidilo.ua/news_sitemap_uk.xml` | Not configured | Uses Ukrainian monthly sitemap filters | Existing media source. |
| `tyzhden` | media | Manual validation required | Not configured | `https://tyzhden.ua/wp-sitemap.xml` | Not configured | Uses post sitemap filters | Existing media source. |
| `chesno` | media | Manual validation required | Not configured | `https://www.chesno.org/sitemap.xml` | Not configured | Uses post sitemap filters | Existing media source. |
| `nabu` | law enforcement | Manual validation required | Not configured | Not configured | `https://nabu.gov.ua/news/` | Include `/news/<slug>/`; exclude English, search, archives, orders, summonses, wanted notices, document files | Official news section only. |
| `hcac` | court | Manual validation required | Not configured | Not configured | `https://hcac.court.gov.ua/hcac/pres-centr/news/`, `https://hcac.court.gov.ua/hcac/info_sud/news` | Include official news IDs under those paths | Court portal news sections only. |
| `dbr` | law enforcement | Manual validation required | Not configured | Not configured | `https://dbr.gov.ua/news` | Include `/news/<slug>`; exclude assets, admin, search, documents, images | Official news only. |
| `nazk` | institution | Manual validation required | Not configured | Not configured | `https://nazk.gov.ua/uk/novyny/` | Include `/uk/novyny/<slug>/`; exclude declarations, dashboards, documents, uploads | Registry and document areas are excluded. |
| `arma` | institution | Manual validation required | Not configured | Not configured | `https://arma.gov.ua/news` | Include `/news/typical/<slug>`; exclude document files | Official news path only. |
| `gp` | law enforcement | Manual validation required | Not configured | Not configured | `https://gp.gov.ua/ua/posts` | Include `/ua/posts/<slug>`; exclude regional subdomains, documents, search, files | Official post paths only; needs live validation. |
| `ssu` | law enforcement | Manual validation required | Not configured | Not configured | `https://ssu.gov.ua/novyny` | Include `/novyny/<slug>`; exclude English, galleries, search | Official news path only. |
| `npu` | law enforcement | Manual validation required | Not configured | Not configured | `https://npu.gov.ua/news` | Include `/news/<slug>`; exclude search, static files, documents | Official news path only. |
| `court-gov` | court | Manual validation required | Not configured | Not configured | `https://court.gov.ua/press/news/` | Include `/press/news/<id>`; exclude decision databases, schedules, search, storage | Avoids registry and schedule crawling. |
| `supreme-court` | court | Manual validation required | Not configured | Not configured | `https://supreme.court.gov.ua/supreme/pres-centr/news/` | Include `/supreme/pres-centr/news/<id>` | Official Supreme Court news section. |
| `ccu` | court | Manual validation required | Not configured | Not configured | `https://ccu.gov.ua/storinka/novyny` | Include `/novyna/<slug>` and validated news publication paths; exclude decisions, document libraries, files | Canonical news paths need live validation. |
| `rada` | parliament | Manual validation required | Not configured | Not configured | `https://www.rada.gov.ua/news/Novyny/`, `https://www.rada.gov.ua/news/news_kom/` | Include `.html` news items; exclude law databases, bill cards, uploads, files, search | Avoids `zakon.rada.gov.ua` and bill registry crawling. |
| `kmu` | government | Manual validation required | Not configured | Not configured | `https://www.kmu.gov.ua/timeline?&type=posts` | Include `/news/<slug>`; exclude `/npas`, petitions, storage, search | Official post timeline only. |
| `president` | government | Manual validation required | Not configured | Not configured | `https://www.president.gov.ua/news` | Include `/news/<slug>-<id>`; exclude documents, petitions, photo/video galleries | Text news only. |
| `rnbo` | government | Manual validation required | Not configured | Not configured | `https://www.rnbo.gov.ua/ua/Diialnist/` | Include `/ua/Diialnist/<id>.html`; exclude files and documents | Activity/news-like pages only. |

## Problematic Or Unsupported Sources

| Source | Status | Reason |
| --- | --- | --- |
| `sap.gov.ua` | Manual review required | Prior probing timed out and search results primarily exposed Telegram/social mirrors. Do not add until an official RSS, sitemap, or news section is verified. |
| `itd.rada.gov.ua` | Unsupported | Appears to be an electronic cabinet / bill-information system, not a news source. Excluded to avoid bill and registry crawling. |
