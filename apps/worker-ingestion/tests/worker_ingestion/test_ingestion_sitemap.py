import gzip
from datetime import UTC, datetime

import pytest
from conftest import FakeFetcher, fetch_result, source_config
from worker_ingestion.config import IngestionConfig
from worker_ingestion.discovery.sitemap import (
    discover_article_urls,
    effective_discovery_limit,
    parse_feed,
    parse_section_article_links,
    parse_sitemap,
)
from worker_ingestion.discovery.sources import SourceConfig


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


def test_parse_feed_supports_rss_and_atom() -> None:
    rss = b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <item>
          <link>https://example.ua/news/rss</link>
          <pubDate>Mon, 01 Jun 2026 12:00:00 +0000</pubDate>
        </item>
      </channel>
    </rss>
    """
    atom = b"""<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <link rel="alternate" href="/news/atom"/>
        <updated>2026-06-01T13:00:00+00:00</updated>
      </entry>
    </feed>
    """

    assert parse_feed(rss, feed_url="https://example.ua/feed.xml") == [
        ("https://example.ua/news/rss", datetime(2026, 6, 1, 12, tzinfo=UTC))
    ]
    assert parse_feed(atom, feed_url="https://example.ua/feed.xml") == [
        ("https://example.ua/news/atom", datetime(2026, 6, 1, 13, tzinfo=UTC))
    ]


def test_parsers_normalize_naive_dates_to_utc() -> None:
    sitemap = b"""<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url>
        <loc>https://example.ua/news/item</loc>
        <lastmod>2026-06-01T10:00:00</lastmod>
      </url>
    </urlset>
    """
    rss = b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <item>
          <link>https://example.ua/news/rss</link>
          <pubDate>Mon, 01 Jun 2026 12:00:00</pubDate>
        </item>
      </channel>
    </rss>
    """

    _, sitemap_urls = parse_sitemap(sitemap, sitemap_url="https://example.ua/sitemap.xml")
    feed_urls = parse_feed(rss, feed_url="https://example.ua/feed.xml")

    assert sitemap_urls == [("https://example.ua/news/item", datetime(2026, 6, 1, 10, tzinfo=UTC))]
    assert feed_urls == [("https://example.ua/news/rss", datetime(2026, 6, 1, 12, tzinfo=UTC))]


def test_parse_section_article_links_normalizes_and_deduplicates_links() -> None:
    html = """<html><body>
      <a href="/news/one#comments">One</a>
      <a href="https://example.ua/news/one">Duplicate</a>
      <a href="mailto:press@example.ua">Email</a>
      <a href="https://other.ua/news/two">External</a>
    </body></html>"""

    assert parse_section_article_links(html, section_url="https://example.ua/news/") == [
        "https://example.ua/news/one",
    ]


def test_parse_section_article_links_extracts_same_host_json_urls() -> None:
    payload = """
    {
      "data": {
        "2026-06-02": [
          {"url": "https://example.ua/news/item", "image": "https://example.ua/img/item.jpg"},
          {"url": "/news/other"},
          {"url": "https://other.example/news/ignored"}
        ]
      }
    }
    """

    assert parse_section_article_links(payload, section_url="https://example.ua/api/timeline") == [
        "https://example.ua/news/item",
        "https://example.ua/img/item.jpg",
        "https://example.ua/news/other",
    ]


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
    assert [url.discovery_method for url in urls] == ["sitemap"]


@pytest.mark.asyncio
async def test_discover_article_urls_compares_naive_lastmod_with_aware_window() -> None:
    articles = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url>
        <loc>https://example.ua/news/in-window</loc>
        <lastmod>2026-06-01T12:00:00</lastmod>
      </url>
    </urlset>"""

    urls = await discover_article_urls(
        source_config(),
        FakeFetcher(
            {
                "https://example.ua/sitemap.xml": fetch_result(
                    "https://example.ua/sitemap.xml", articles, "application/xml"
                ),
            }
        ),
        IngestionConfig(),
        since=datetime(2026, 5, 31, tzinfo=UTC),
    )

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


def test_effective_discovery_limit_uses_high_cap_for_date_bounded_runs() -> None:
    assert (
        effective_discovery_limit(
            IngestionConfig(max_sitemap_urls_per_source=500),
            since=datetime(2025, 1, 1, tzinfo=UTC),
            until=datetime(2025, 12, 31, tzinfo=UTC),
        )
        == 10_000
    )


@pytest.mark.asyncio
async def test_discover_article_urls_reaches_in_window_archive_after_old_sitemaps() -> None:
    source = SourceConfig(
        slug="example",
        name="Example",
        base_url="https://example.ua",
        sitemap_urls=("https://example.ua/root.xml",),
        sitemap_url_patterns=(r"https://example\.ua/sitemaps/posts/\d{4}/\d{1,2}\.xml",),
        include_url_patterns=(r"https://example\.ua/news/.+",),
    )
    root = """<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <sitemap><loc>https://example.ua/sitemaps/posts/2013/11.xml</loc></sitemap>
      <sitemap><loc>https://example.ua/sitemaps/posts/2026/6.xml</loc></sitemap>
    </sitemapindex>"""
    old_articles = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://example.ua/news/old</loc><lastmod>2013-11-01T12:00:00+00:00</lastmod></url>
    </urlset>"""
    new_articles = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://example.ua/news/new</loc><lastmod>2026-06-01T12:00:00+00:00</lastmod></url>
    </urlset>"""
    fetcher = FakeFetcher(
        {
            "https://example.ua/root.xml": fetch_result(
                "https://example.ua/root.xml", root, "application/xml"
            ),
            "https://example.ua/sitemaps/posts/2026/6.xml": fetch_result(
                "https://example.ua/sitemaps/posts/2026/6.xml", new_articles, "application/xml"
            ),
            "https://example.ua/sitemaps/posts/2013/11.xml": fetch_result(
                "https://example.ua/sitemaps/posts/2013/11.xml", old_articles, "application/xml"
            ),
        }
    )

    urls = await discover_article_urls(
        source,
        fetcher,
        IngestionConfig(max_sitemap_urls_per_source=1),
        since=datetime(2026, 1, 1, tzinfo=UTC),
        until=datetime(2026, 12, 31, tzinfo=UTC),
    )

    assert fetcher.requested_urls == [
        "https://example.ua/root.xml",
        "https://example.ua/sitemaps/posts/2026/6.xml",
    ]
    assert [url.url for url in urls] == ["https://example.ua/news/new"]


@pytest.mark.asyncio
async def test_discover_article_urls_prefers_feeds_for_daily_discovery() -> None:
    source = SourceConfig(
        slug="example",
        name="Example",
        base_url="https://example.ua",
        sitemap_urls=("https://example.ua/sitemap.xml",),
        rss_urls=("https://example.ua/feed.xml",),
        include_url_patterns=(r"https://example\.ua/news/[^/?#]+/?$",),
    )
    feed = """<rss version="2.0"><channel>
      <item><link>https://example.ua/news/from-feed</link></item>
    </channel></rss>"""
    sitemap = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://example.ua/news/from-sitemap</loc></url>
    </urlset>"""
    fetcher = FakeFetcher(
        {
            "https://example.ua/feed.xml": fetch_result(
                "https://example.ua/feed.xml", feed, "application/rss+xml"
            ),
            "https://example.ua/sitemap.xml": fetch_result(
                "https://example.ua/sitemap.xml", sitemap, "application/xml"
            ),
        }
    )

    urls = await discover_article_urls(
        source,
        fetcher,
        IngestionConfig(max_sitemap_urls_per_source=1),
    )

    assert fetcher.requested_urls == ["https://example.ua/feed.xml"]
    assert [(url.url, url.discovery_method) for url in urls] == [
        ("https://example.ua/news/from-feed", "feed"),
    ]


@pytest.mark.asyncio
async def test_discover_article_urls_uses_feeds_and_section_pages() -> None:
    source = SourceConfig(
        slug="example",
        name="Example",
        base_url="https://example.ua",
        rss_urls=("https://example.ua/feed.xml",),
        section_urls=("https://example.ua/news/",),
        include_url_patterns=(r"https://example\.ua/news/[^/?#]+/?$",),
        exclude_url_patterns=(r"\.pdf(?:$|\?)", r"/search"),
    )
    feed = """<rss version="2.0"><channel>
      <item><link>https://example.ua/news/from-feed</link></item>
      <item><link>https://example.ua/search?q=noise</link></item>
    </channel></rss>"""
    section = """<html><body>
      <a href="/news/from-section">Section</a>
      <a href="/uploads/file.pdf">PDF</a>
      <a href="/news/from-feed">Duplicate</a>
    </body></html>"""

    urls = await discover_article_urls(
        source,
        FakeFetcher(
            {
                "https://example.ua/feed.xml": fetch_result(
                    "https://example.ua/feed.xml", feed, "application/rss+xml"
                ),
                "https://example.ua/news/": fetch_result("https://example.ua/news/", section),
            }
        ),
        IngestionConfig(max_sitemap_urls_per_source=10),
    )

    assert [(url.url, url.discovery_method) for url in urls] == [
        ("https://example.ua/news/from-feed", "feed"),
        ("https://example.ua/news/from-section", "section"),
    ]
