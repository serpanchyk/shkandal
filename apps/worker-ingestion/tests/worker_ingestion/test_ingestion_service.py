import logging
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from conftest import (
    FakeArticleRepository,
    FakeFetcher,
    failed_fetch_result,
    fetch_result,
    source_config,
)
from worker_ingestion.config import IngestionConfig
from worker_ingestion.discovery.sources import SourceConfig
from worker_ingestion.persistence.articles import ArticleInput
from worker_ingestion.service import IngestionWorker


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


@pytest.mark.asyncio
async def test_existing_discovered_article_is_skipped_before_fetch() -> None:
    sitemap = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>http://www.example.ua/news/item/?utm_source=tg#comments</loc></url>
      <url><loc>https://example.ua/news/new</loc></url>
    </urlset>
    """
    new_article_html = """<html lang="uk"><head><meta property="og:title" content="Нова"></head>
    <body><article><p>Текст.</p></article></body></html>
    """
    existing_identity_url = "https://example.ua/news/item"
    repository = FakeArticleRepository()
    repository.articles[existing_identity_url] = ArticleInput(
        source_id=uuid4(),
        url="https://example.ua/news/item",
        identity_url=existing_identity_url,
        title="Вже збережена",
        lead=None,
        published_at=datetime(2026, 6, 1, tzinfo=UTC),
        fetched_at=datetime(2026, 6, 1, tzinfo=UTC),
        source_language="uk",
        raw_html="<html></html>",
        extracted_text="Текст.",
        remote_image_url=None,
        remote_image_metadata={},
        source_metadata={},
    )
    fetcher = FakeFetcher(
        {
            "https://example.ua/sitemap.xml": fetch_result(
                "https://example.ua/sitemap.xml",
                sitemap,
                "application/xml",
            ),
            "https://example.ua/news/new": fetch_result(
                "https://example.ua/news/new",
                new_article_html,
            ),
        }
    )
    worker = IngestionWorker(
        config=IngestionConfig(),
        fetcher=fetcher,
        repository=repository,
        sources=(source_config(),),
    )

    stats = await worker.run_once(source_slug="example")

    assert stats.discovered_articles == 2
    assert stats.skipped_existing_articles == 1
    assert stats.stored_articles == 1
    assert stats.failed_articles == 0
    assert fetcher.requested_urls == [
        "https://example.ua/sitemap.xml",
        "https://example.ua/news/new",
    ]
    assert set(repository.articles) == {
        "https://example.ua/news/item",
        "https://example.ua/news/new",
    }


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
    assert failed.raw_html is None
    assert failed.fetch_status == "failed"
    assert failed.fetch_attempt_count == 1
    assert failed.next_fetch_at is not None
    assert failed.last_fetch_error == "server_error"
    assert failed.source_metadata["fetch_error"] == "server_error"


@pytest.mark.asyncio
async def test_due_failed_article_is_retried_and_becomes_successful() -> None:
    article_url = "https://example.ua/news/retry"
    sitemap = f"""<urlset><url><loc>{article_url}</loc></url></urlset>"""
    fetcher = FakeFetcher(
        {
            "https://example.ua/sitemap.xml": fetch_result(
                "https://example.ua/sitemap.xml",
                sitemap,
                "application/xml",
            ),
            article_url: failed_fetch_result(article_url),
        }
    )
    repository = FakeArticleRepository()
    worker = IngestionWorker(
        config=IngestionConfig(),
        fetcher=fetcher,
        repository=repository,
        sources=(source_config(),),
    )

    first_stats = await worker.run_once(source_slug="example")
    fetcher.responses["https://example.ua/sitemap.xml"] = fetch_result(
        "https://example.ua/sitemap.xml",
        "<urlset></urlset>",
        "application/xml",
    )
    fetcher.responses[article_url] = fetch_result(
        article_url,
        "<html><body><article><p>Recovered.</p></article></body></html>",
    )
    second_stats = await worker.run_once(source_slug="example")

    assert first_stats.failed_articles == 1
    assert second_stats.stored_articles == 1
    assert repository.articles[article_url].fetch_status == "succeeded"
    assert repository.articles[article_url].fetch_attempt_count == 2


@pytest.mark.asyncio
async def test_source_failure_does_not_abort_later_sources() -> None:
    good_section_url = "https://good.example/news"
    good_article_url = "https://good.example/news/item"
    fetcher = FakeFetcher(
        {
            good_section_url: fetch_result(
                good_section_url,
                f'<a href="{good_article_url}">item</a>',
            ),
            good_article_url: fetch_result(
                good_article_url,
                "<html><body><article><p>Stored.</p></article></body></html>",
            ),
        }
    )
    repository = FakeArticleRepository()
    worker = IngestionWorker(
        config=IngestionConfig(),
        fetcher=fetcher,
        repository=repository,
        sources=(
            SourceConfig(
                slug="bad",
                name="Bad",
                base_url="https://bad.example",
                section_urls=("https://bad.example/news",),
            ),
            SourceConfig(
                slug="good",
                name="Good",
                base_url="https://good.example",
                section_urls=(good_section_url,),
                include_url_patterns=(r"https://good\.example/news/.+",),
            ),
        ),
    )

    stats = await worker.run_once()

    assert stats.processed_sources == 2
    assert stats.failed_sources == 1
    assert stats.stored_articles == 1


@pytest.mark.asyncio
async def test_date_bounded_section_article_outside_extracted_window_is_skipped() -> None:
    section_url = "https://example.ua/news/"
    article_url = "https://example.ua/news/current"
    section = f"""<html><body><a href="{article_url}">Current section item</a></body></html>"""
    article_html = """<!doctype html>
    <html lang="uk">
      <head>
        <meta property="og:title" content="Поточна новина">
        <meta property="article:published_time" content="2025-02-15T12:00:00+00:00">
      </head>
      <body><article><p>Текст поза запитаним вікном.</p></article></body>
    </html>
    """
    repository = FakeArticleRepository()
    fetcher = FakeFetcher(
        {
            section_url: fetch_result(section_url, section),
            article_url: fetch_result(article_url, article_html),
        }
    )
    worker = IngestionWorker(
        config=IngestionConfig(),
        fetcher=fetcher,
        repository=repository,
        sources=(
            SourceConfig(
                slug="example",
                name="Example Institution",
                base_url="https://example.ua",
                section_urls=(section_url,),
                include_url_patterns=(r"https://example\.ua/news/.+",),
                source_type="institution",
            ),
        ),
    )

    stats = await worker.run_once(
        source_slug="example",
        since=datetime(2025, 1, 1, tzinfo=UTC),
        until=datetime(2025, 1, 31, 23, 59, 59, tzinfo=UTC),
    )

    assert stats.discovered_articles == 1
    assert stats.stored_articles == 0
    assert stats.failed_articles == 0
    assert stats.skipped_out_of_window_articles == 1
    assert repository.articles == {}
    assert fetcher.requested_urls == [section_url, article_url]


@pytest.mark.asyncio
async def test_run_once_logs_source_progress_and_article_failures(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sitemap = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://example.ua/news/fails</loc></url>
    </urlset>
    """
    repository = FakeArticleRepository()
    worker = IngestionWorker(
        config=IngestionConfig(service_name="ingestion-test"),
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
            }
        ),
        repository=repository,
        sources=(source_config(),),
    )

    with caplog.at_level(logging.INFO, logger="ingestion-test"):
        stats = await worker.run_once(source_slug="example")

    assert stats.discovered_articles == 1
    assert [record.message for record in caplog.records if record.name == "ingestion-test"] == [
        "worker_ingestion_source_started",
        "worker_ingestion_source_discovered",
        "worker_ingestion_article_fetch_failed",
        "worker_ingestion_source_finished",
    ]
    article_failure = next(
        record
        for record in caplog.records
        if record.message == "worker_ingestion_article_fetch_failed"
    )
    assert getattr(article_failure, "source_slug") == "example"
    assert getattr(article_failure, "article_url") == "https://example.ua/news/fails"
    assert getattr(article_failure, "status_code") == 500
    assert getattr(article_failure, "fetch_error") == "server_error"
