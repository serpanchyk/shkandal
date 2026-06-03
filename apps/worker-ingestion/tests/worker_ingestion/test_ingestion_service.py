import logging

import pytest
from conftest import (
    FakeArticleRepository,
    FakeFetcher,
    failed_fetch_result,
    fetch_result,
    source_config,
)
from worker_ingestion.config import IngestionConfig
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
    assert failed.source_metadata["fetch_error"] == "server_error"


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
