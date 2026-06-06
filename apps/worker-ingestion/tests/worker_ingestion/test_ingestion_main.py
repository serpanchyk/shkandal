import gzip
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from worker_ingestion.articles.extractor import extract_article
from worker_ingestion.articles.identity import normalize_article_url
from worker_ingestion.config import IngestionConfig
from worker_ingestion.discovery.sitemap import discover_article_urls, parse_sitemap
from worker_ingestion.discovery.sources import MEDIA_SOURCES, SourceConfig
from worker_ingestion.persistence.articles import ArticleInput, SourceInput
from worker_ingestion.service import IngestionWorker
from worker_ingestion.transport import FetchResult


class FakeFetcher:
    def __init__(self, responses: dict[str, FetchResult]) -> None:
        self.responses = responses
        self.requested_urls: list[str] = []

    async def fetch(self, url: str) -> FetchResult:
        self.requested_urls.append(url)
        return self.responses[url]


class FakeArticleRepository:
    def __init__(self) -> None:
        self.source_ids: dict[str, UUID] = {}
        self.articles: dict[str, ArticleInput] = {}

    async def ensure_source(self, source: SourceInput) -> UUID:
        source_id = self.source_ids.get(source.slug)
        if source_id is None:
            source_id = uuid4()
            self.source_ids[source.slug] = source_id
        return source_id

    async def skippable_identity_urls(
        self,
        identity_urls: set[str],
        *,
        max_attempts: int,
        now: datetime | None = None,
    ) -> set[str]:
        now = now or datetime.now(UTC)
        skippable: set[str] = set()
        for identity_url in set(self.articles).intersection(identity_urls):
            article = self.articles[identity_url]
            next_fetch_at = article.next_fetch_at
            if (
                article.fetch_status == "succeeded"
                or article.fetch_attempt_count >= max_attempts
                or (next_fetch_at is not None and next_fetch_at > now)
            ):
                skippable.add(identity_url)
        return skippable

    async def due_failed_article_urls(
        self,
        source_id: UUID,
        *,
        max_attempts: int,
        limit: int,
        now: datetime | None = None,
    ) -> tuple[str, ...]:
        now = now or datetime.now(UTC)
        return tuple(
            article.url
            for article in self.articles.values()
            if article.source_id == source_id
            and article.fetch_status == "failed"
            and article.fetch_attempt_count < max_attempts
            and (article.next_fetch_at is None or article.next_fetch_at <= now)
        )[:limit]

    async def upsert_article(self, article: ArticleInput) -> None:
        existing = self.articles.get(article.identity_url)
        if existing is None:
            self.articles[article.identity_url] = article
            return

        self.articles[article.identity_url] = ArticleInput(
            source_id=existing.source_id,
            url=existing.url,
            identity_url=existing.identity_url,
            title=article.title or existing.title,
            lead=article.lead or existing.lead,
            published_at=article.published_at or existing.published_at,
            fetched_at=article.fetched_at or existing.fetched_at,
            source_language=article.source_language or existing.source_language,
            raw_html=article.raw_html or existing.raw_html,
            extracted_text=article.extracted_text or existing.extracted_text,
            remote_image_url=article.remote_image_url or existing.remote_image_url,
            remote_image_metadata={
                **existing.remote_image_metadata,
                **article.remote_image_metadata,
            },
            source_metadata={**existing.source_metadata, **article.source_metadata},
            fetch_status=article.fetch_status,
            fetch_attempt_count=existing.fetch_attempt_count + 1,
            next_fetch_at=article.next_fetch_at,
            last_fetch_error=article.last_fetch_error,
        )


def source_config() -> SourceConfig:
    return SourceConfig(
        slug="example",
        name="Example Media",
        base_url="https://example.ua",
        sitemap_urls=("https://example.ua/sitemap.xml",),
        sitemap_url_patterns=(r"https://example\.ua/articles\.xml",),
        include_url_patterns=(r"https?://(www\.)?example\.ua/news/.+",),
    )


def fetch_result(url: str, body: str, content_type: str = "text/html") -> FetchResult:
    return FetchResult(
        url=url,
        status_code=200,
        content=body.encode(),
        text=body,
        headers={"content-type": content_type},
        fetched_at=datetime(2026, 6, 1, tzinfo=UTC),
    )


def failed_fetch_result(url: str) -> FetchResult:
    return FetchResult(
        url=url,
        status_code=500,
        content=b"",
        text="",
        headers={"content-type": "text/html"},
        fetched_at=datetime(2026, 6, 1, tzinfo=UTC),
        error="server_error",
    )


@pytest.mark.asyncio
async def test_run_once_smoke() -> None:
    result = await IngestionConfig(service_name="ingestion-test").service_status()

    assert result == {"service": "ingestion-test", "status": "ok"}


@pytest.mark.asyncio
async def test_duplicate_url_variants_ingest_one_article() -> None:
    sitemap = """<?xml version="1.0" encoding="UTF-8"?>
    <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <sitemap><loc>https://example.ua/articles.xml</loc></sitemap>
    </sitemapindex>
    """
    articles_sitemap = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://www.example.ua/news/item?utm_source=tg#comments</loc></url>
      <url><loc>http://example.ua/news/item/</loc></url>
    </urlset>
    """
    article_html = """<!doctype html>
    <html lang="uk">
      <head>
        <link rel="canonical" href="https://example.ua/news/item/">
        <meta property="og:title" content="Заголовок">
        <meta property="og:description" content="Короткий опис">
        <meta property="article:published_time" content="2026-06-01T12:30:00+00:00">
        <meta property="og:image" content="https://example.ua/image.jpg">
      </head>
      <body><article><p>Перший абзац.</p><p>Другий абзац.</p></article></body>
    </html>
    """
    first_url = "https://www.example.ua/news/item?utm_source=tg#comments"
    second_url = "http://example.ua/news/item/"
    repository = FakeArticleRepository()
    worker = IngestionWorker(
        config=IngestionConfig(),
        fetcher=FakeFetcher(
            {
                "https://example.ua/sitemap.xml": fetch_result(
                    "https://example.ua/sitemap.xml",
                    sitemap,
                    "application/xml",
                ),
                "https://example.ua/articles.xml": fetch_result(
                    "https://example.ua/articles.xml",
                    articles_sitemap,
                    "application/xml",
                ),
                first_url: fetch_result(first_url, article_html),
                second_url: fetch_result(second_url, article_html),
            }
        ),
        repository=repository,
        sources=(source_config(),),
    )

    stats = await worker.run_once(source_slug="example")

    assert stats.discovered_articles == 2
    assert stats.stored_articles == 2
    assert len(repository.articles) == 1
    article = next(iter(repository.articles.values()))
    assert article.url == first_url
    assert article.identity_url == "https://example.ua/news/item"
    assert article.title == "Заголовок"
    assert article.lead == "Короткий опис"
    assert article.remote_image_url == "https://example.ua/image.jpg"
    assert article.extracted_text == "Перший абзац.\n\nДругий абзац."


@pytest.mark.asyncio
async def test_failed_article_fetch_is_persisted_without_aborting_source() -> None:
    sitemap = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://example.ua/news/fails</loc></url>
      <url><loc>https://example.ua/news/works</loc></url>
    </urlset>
    """
    article_html = """<html lang="uk"><head><meta property="og:title" content="Працює"></head>
    <body><article><p>Текст.</p></article></body></html>
    """
    repository = FakeArticleRepository()
    worker = IngestionWorker(
        config=IngestionConfig(),
        fetcher=FakeFetcher(
            {
                "https://example.ua/sitemap.xml": fetch_result(
                    "https://example.ua/sitemap.xml",
                    sitemap,
                    "application/xml",
                ),
                "https://example.ua/news/fails": failed_fetch_result(
                    "https://example.ua/news/fails"
                ),
                "https://example.ua/news/works": fetch_result(
                    "https://example.ua/news/works",
                    article_html,
                ),
            }
        ),
        repository=repository,
        sources=(source_config(),),
    )

    stats = await worker.run_once(source_slug="example")

    assert stats.discovered_articles == 2
    assert stats.stored_articles == 1
    assert stats.failed_articles == 1
    assert len(repository.articles) == 2
    failed = repository.articles["https://example.ua/news/fails"]
    assert failed.url == "https://example.ua/news/fails"
    assert failed.raw_html is None
    assert failed.source_metadata["fetch_error"] == "server_error"


def test_normalize_article_url_removes_common_duplicate_variants() -> None:
    assert (
        normalize_article_url("http://www.example.ua//news/item/?utm_source=tg#comments")
        == "https://example.ua/news/item"
    )


def test_normalize_article_url_preserves_unknown_query_params() -> None:
    assert (
        normalize_article_url("https://example.ua/news/item?print=1&utm_medium=social")
        == "https://example.ua/news/item?print=1"
    )


def test_normalize_article_url_normalizes_percent_encoding() -> None:
    assert (
        normalize_article_url("https://www.example.ua/news/%D1%82%D0%B5%D1%81%D1%82/")
        == "https://example.ua/news/%D1%82%D0%B5%D1%81%D1%82"
    )


def test_parse_sitemap_index_and_urlset_with_namespaces() -> None:
    sitemap_index = b"""<?xml version="1.0" encoding="UTF-8"?>
    <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <sitemap><loc>https://example.ua/articles.xml</loc></sitemap>
    </sitemapindex>
    """
    urlset = b"""<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url>
        <loc>https://example.ua/news/item</loc>
        <lastmod>2026-06-01T10:00:00+00:00</lastmod>
      </url>
    </urlset>
    """

    nested_sitemaps, urls = parse_sitemap(
        sitemap_index, sitemap_url="https://example.ua/sitemap.xml"
    )
    assert nested_sitemaps == ["https://example.ua/articles.xml"]
    assert urls == []

    nested_sitemaps, urls = parse_sitemap(
        gzip.compress(urlset), sitemap_url="https://example.ua/articles.xml"
    )
    assert nested_sitemaps == []
    assert urls == [("https://example.ua/news/item", datetime(2026, 6, 1, 10, tzinfo=UTC))]


def test_parse_sitemap_returns_empty_entries_for_invalid_xml() -> None:
    assert parse_sitemap(b"<not xml", sitemap_url="https://example.ua/bad.xml") == ([], [])


@pytest.mark.asyncio
async def test_discover_article_urls_recurses_filters_and_applies_date_window() -> None:
    source = SourceConfig(
        slug="example",
        name="Example",
        base_url="https://example.ua",
        sitemap_urls=("https://example.ua/root.xml",),
        sitemap_url_patterns=(r"https://example\.ua/articles-\d+\.xml",),
        include_url_patterns=(r"/news/",),
        exclude_url_patterns=(r"/ru/",),
    )
    root = """<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <sitemap><loc>https://example.ua/ignored.xml</loc></sitemap>
      <sitemap><loc>https://example.ua/articles-1.xml</loc></sitemap>
    </sitemapindex>"""
    articles = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url>
        <loc>https://example.ua/news/in-window</loc>
        <lastmod>2026-06-01T12:00:00+00:00</lastmod>
      </url>
      <url>
        <loc>https://example.ua/news/too-old</loc>
        <lastmod>2026-05-30T12:00:00+00:00</lastmod>
      </url>
      <url><loc>https://example.ua/ru/news/excluded</loc></url>
      <url><loc>https://example.ua/about</loc></url>
    </urlset>"""
    assert (
        parse_sitemap(articles.encode(), sitemap_url="https://example.ua/articles-1.xml")[1][0][0]
        == "https://example.ua/news/in-window"
    )

    fetcher = FakeFetcher(
        {
            "https://example.ua/root.xml": fetch_result(
                "https://example.ua/root.xml", root, "application/xml"
            ),
            "https://example.ua/articles-1.xml": fetch_result(
                "https://example.ua/articles-1.xml", articles, "application/xml"
            ),
        }
    )
    urls = await discover_article_urls(
        source,
        fetcher,
        IngestionConfig(),
        since=datetime(2026, 5, 31, tzinfo=UTC),
        until=datetime(2026, 6, 2, tzinfo=UTC),
    )

    assert fetcher.requested_urls == [
        "https://example.ua/root.xml",
        "https://example.ua/articles-1.xml",
    ]
    assert [url.url for url in urls] == ["https://example.ua/news/in-window"]


@pytest.mark.asyncio
async def test_discover_article_urls_respects_source_limit() -> None:
    sitemap = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://example.ua/news/one</loc></url>
      <url><loc>https://example.ua/news/two</loc></url>
      <url><loc>https://example.ua/news/three</loc></url>
    </urlset>"""

    urls = await discover_article_urls(
        source_config(),
        FakeFetcher(
            {
                "https://example.ua/sitemap.xml": fetch_result(
                    "https://example.ua/sitemap.xml", sitemap, "application/xml"
                ),
            }
        ),
        IngestionConfig(max_sitemap_urls_per_source=2),
    )

    assert [url.url for url in urls] == [
        "https://example.ua/news/one",
        "https://example.ua/news/two",
    ]


def test_extract_article_uses_generic_fallbacks() -> None:
    html = """<html lang="uk"><head>
      <title>Ignored</title>
    </head><body>
      <article>
        <h1>Fallback title</h1>
        <time datetime="2026-06-01T12:00:00+00:00">1 червня</time>
        <p>Перший абзац.</p>
        <p>Другий абзац.</p>
      </article>
    </body></html>"""

    article = extract_article(source_config(), url="https://example.ua/news/fallback", html=html)

    assert article.title == "Fallback title"
    assert article.published_at == datetime(2026, 6, 1, 12, tzinfo=UTC)
    assert article.source_language == "uk"
    assert article.extracted_text == "Перший абзац.\n\nДругий абзац."


def test_media_source_catalog_uses_current_known_sitemap_roots() -> None:
    sources = {source.slug: source for source in MEDIA_SOURCES}

    assert sources["pravda"].sitemap_urls == ("https://www.pravda.com.ua/sitemap/sitemap.xml",)
    assert (
        r"https://nashigroshi\.org/post-sitemap\d*\.xml"
        in sources["nashigroshi"].sitemap_url_patterns
    )
    assert sources["slovoidilo"].sitemap_urls == (
        "https://www.slovoidilo.ua/sitemap_index_uk.xml",
        "https://www.slovoidilo.ua/news_sitemap_uk.xml",
    )
