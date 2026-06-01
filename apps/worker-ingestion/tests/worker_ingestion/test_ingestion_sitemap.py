import gzip
from datetime import UTC, datetime

import pytest
from conftest import FakeFetcher, fetch_result, source_config
from worker_ingestion.config import IngestionConfig
from worker_ingestion.sitemap import discover_article_urls, parse_sitemap
from worker_ingestion.sources import SourceConfig


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
