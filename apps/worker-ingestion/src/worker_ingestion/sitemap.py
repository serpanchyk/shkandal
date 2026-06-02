"""Sitemap discovery."""

from __future__ import annotations

import gzip
import re
import xml.etree.ElementTree as ET
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from worker_ingestion.config import IngestionConfig
from worker_ingestion.sources import SourceConfig
from worker_ingestion.transport import Fetcher


@dataclass(frozen=True)
class SitemapArticleUrl:
    url: str
    discovery_url: str
    discovery_method: str
    lastmod: datetime | None = None

    @property
    def sitemap_url(self) -> str:
        """Backward-compatible discovery URL for existing storage metadata."""

        return self.discovery_url


async def discover_article_urls(
    source: SourceConfig,
    fetcher: Fetcher,
    config: IngestionConfig,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[SitemapArticleUrl]:
    """Discover likely article URLs from source sitemaps, feeds, and sections."""

    articles: list[SitemapArticleUrl] = []
    seen_article_urls: set[str] = set()

    sitemap_articles = await _discover_sitemap_article_urls(
        source,
        fetcher,
        config,
        since=since,
        until=until,
    )
    _append_unique(
        articles, sitemap_articles, seen_article_urls, limit=config.max_sitemap_urls_per_source
    )

    if len(articles) < config.max_sitemap_urls_per_source:
        feed_articles = await _discover_feed_article_urls(
            source,
            fetcher,
            since=since,
            until=until,
        )
        _append_unique(
            articles,
            feed_articles,
            seen_article_urls,
            limit=config.max_sitemap_urls_per_source,
        )

    if len(articles) < config.max_sitemap_urls_per_source:
        section_articles = await _discover_section_article_urls(source, fetcher)
        _append_unique(
            articles,
            section_articles,
            seen_article_urls,
            limit=config.max_sitemap_urls_per_source,
        )

    return articles


async def _discover_sitemap_article_urls(
    source: SourceConfig,
    fetcher: Fetcher,
    config: IngestionConfig,
    *,
    since: datetime | None,
    until: datetime | None,
) -> list[SitemapArticleUrl]:
    queue = deque(source.sitemap_urls)
    seen_sitemaps: set[str] = set()
    articles: list[SitemapArticleUrl] = []
    while queue and len(articles) < config.max_sitemap_urls_per_source:
        sitemap_url = queue.popleft()
        if sitemap_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sitemap_url)

        response = await fetcher.fetch(sitemap_url)
        if not response.ok:
            continue
        nested_sitemaps, urls = parse_sitemap(response.content, sitemap_url=sitemap_url)
        for nested in nested_sitemaps:
            if _matches_any(nested, source.sitemap_url_patterns):
                queue.append(nested)
        for url, lastmod in urls:
            if not _in_window(lastmod, since=since, until=until):
                continue
            if not _is_allowed_article_url(url, source):
                continue
            articles.append(
                SitemapArticleUrl(
                    url=url,
                    discovery_url=sitemap_url,
                    discovery_method="sitemap",
                    lastmod=lastmod,
                )
            )
            if len(articles) >= config.max_sitemap_urls_per_source:
                break

    return articles


async def _discover_feed_article_urls(
    source: SourceConfig,
    fetcher: Fetcher,
    *,
    since: datetime | None,
    until: datetime | None,
) -> list[SitemapArticleUrl]:
    articles: list[SitemapArticleUrl] = []
    for feed_url in source.rss_urls:
        response = await fetcher.fetch(feed_url)
        if not response.ok:
            continue
        for url, published_at in parse_feed(response.content, feed_url=feed_url):
            if not _in_window(published_at, since=since, until=until):
                continue
            if not _is_allowed_article_url(url, source):
                continue
            articles.append(
                SitemapArticleUrl(
                    url=url,
                    discovery_url=feed_url,
                    discovery_method="feed",
                    lastmod=published_at,
                )
            )
    return articles


async def _discover_section_article_urls(
    source: SourceConfig,
    fetcher: Fetcher,
) -> list[SitemapArticleUrl]:
    articles: list[SitemapArticleUrl] = []
    for section_url in source.section_urls:
        response = await fetcher.fetch(section_url)
        if not response.ok:
            continue
        for url in parse_section_article_links(response.text, section_url=section_url):
            if not _is_allowed_article_url(url, source):
                continue
            articles.append(
                SitemapArticleUrl(
                    url=url,
                    discovery_url=section_url,
                    discovery_method="section",
                    lastmod=None,
                )
            )
    return articles


def parse_sitemap(
    content: bytes,
    *,
    sitemap_url: str,
) -> tuple[list[str], list[tuple[str, datetime | None]]]:
    """Parse a sitemap or sitemap index into nested sitemaps and URL entries."""

    xml_content = _maybe_decompress(content)
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError:
        return [], []

    tag = _local_name(root.tag)
    if tag == "sitemapindex":
        sitemap_urls = []
        for node in root:
            loc = _child_text(node, "loc")
            if _local_name(node.tag) == "sitemap" and loc:
                sitemap_urls.append(loc)
        return sitemap_urls, []
    if tag != "urlset":
        return [], []

    urls: list[tuple[str, datetime | None]] = []
    for node in root:
        if _local_name(node.tag) != "url":
            continue
        loc = _child_text(node, "loc")
        if not loc:
            continue
        urls.append((loc, _parse_datetime(_child_text(node, "lastmod"))))
    return [], urls


def parse_feed(content: bytes, *, feed_url: str) -> list[tuple[str, datetime | None]]:
    """Parse RSS or Atom feed content into URL/date entries."""

    xml_content = _maybe_decompress(content)
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError:
        return []

    tag = _local_name(root.tag)
    if tag == "rss":
        channel = next((node for node in root if _local_name(node.tag) == "channel"), None)
        if channel is None:
            return []
        entries = []
        for item in channel:
            if _local_name(item.tag) != "item":
                continue
            loc = _child_text(item, "link") or _child_text(item, "guid")
            if not loc:
                continue
            entries.append((urljoin(feed_url, loc), _parse_datetime(_child_text(item, "pubDate"))))
        return entries

    if tag != "feed":
        return []

    entries = []
    for entry in root:
        if _local_name(entry.tag) != "entry":
            continue
        loc = _atom_entry_link(entry)
        if not loc:
            continue
        entries.append(
            (
                urljoin(feed_url, loc),
                _parse_datetime(_child_text(entry, "updated") or _child_text(entry, "published")),
            )
        )
    return entries


def parse_section_article_links(html: str, *, section_url: str) -> list[str]:
    """Extract same-page article links from a source section page."""

    soup = BeautifulSoup(html, "html.parser")
    section_host = urlparse(section_url).netloc
    urls: list[str] = []
    seen: set[str] = set()
    for link in soup.find_all("a", href=True):
        if not isinstance(link, Tag):
            continue
        href = link.get("href")
        if not isinstance(href, str) or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        url = urljoin(section_url, href).split("#", 1)[0]
        if urlparse(url).netloc != section_host:
            continue
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def _maybe_decompress(content: bytes) -> bytes:
    try:
        return gzip.decompress(content)
    except gzip.BadGzipFile:
        return content
    except OSError:
        return content


def _child_text(node: ET.Element, child_name: str) -> str | None:
    for child in node:
        if _local_name(child.tag) == child_name and child.text:
            return child.text.strip()
    return None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return _as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return _parse_rfc2822_datetime(value)


def _parse_rfc2822_datetime(value: str) -> datetime | None:
    from email.utils import parsedate_to_datetime

    try:
        return _as_utc(parsedate_to_datetime(value))
    except (TypeError, ValueError):
        return None


def _in_window(
    lastmod: datetime | None,
    *,
    since: datetime | None,
    until: datetime | None,
) -> bool:
    if lastmod is None:
        return True
    lastmod = _as_utc(lastmod)
    since = _as_utc(since) if since else None
    until = _as_utc(until) if until else None
    if since and lastmod < since:
        return False
    return not (until and lastmod > until)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _is_allowed_article_url(url: str, source: SourceConfig) -> bool:
    if source.include_url_patterns and not _matches_any(url, source.include_url_patterns):
        return False
    return not _matches_any(url, source.exclude_url_patterns)


def _matches_any(value: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, value) for pattern in patterns)


def _atom_entry_link(entry: ET.Element) -> str | None:
    fallback: str | None = None
    for child in entry:
        if _local_name(child.tag) != "link":
            continue
        href = child.attrib.get("href")
        if not href:
            continue
        rel = child.attrib.get("rel")
        if rel in (None, "", "alternate"):
            return href
        fallback = fallback or href
    return fallback


def _append_unique(
    articles: list[SitemapArticleUrl],
    candidates: list[SitemapArticleUrl],
    seen_article_urls: set[str],
    *,
    limit: int,
) -> None:
    for candidate in candidates:
        if candidate.url in seen_article_urls:
            continue
        seen_article_urls.add(candidate.url)
        articles.append(candidate)
        if len(articles) >= limit:
            return
