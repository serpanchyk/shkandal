"""Sitemap discovery."""

from __future__ import annotations

import gzip
import json
import re
import xml.etree.ElementTree as ET
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from worker_ingestion.config import IngestionConfig
from worker_ingestion.discovery.sources import SourceConfig
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
    limit = effective_discovery_limit(config, since=since, until=until)

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
        limit=limit,
    )

    if len(articles) < limit:
        sitemap_articles = await _discover_sitemap_article_urls(
            source,
            fetcher,
            config,
            limit=limit,
            since=since,
            until=until,
        )
        _append_unique(
            articles,
            sitemap_articles,
            seen_article_urls,
            limit=limit,
        )

    if len(articles) < limit:
        section_articles = await _discover_section_article_urls(source, fetcher)
        _append_unique(
            articles,
            section_articles,
            seen_article_urls,
            limit=limit,
        )

    return articles


def effective_discovery_limit(
    config: IngestionConfig,
    *,
    since: datetime | None,
    until: datetime | None,
) -> int:
    """Return the source article discovery cap for this run."""

    if since is not None or until is not None:
        return max(config.max_sitemap_urls_per_source, config.max_backfill_urls_per_source)
    return config.max_sitemap_urls_per_source


async def _discover_sitemap_article_urls(
    source: SourceConfig,
    fetcher: Fetcher,
    config: IngestionConfig,
    *,
    limit: int,
    since: datetime | None,
    until: datetime | None,
) -> list[SitemapArticleUrl]:
    queue = deque(source.sitemap_urls)
    seen_sitemaps: set[str] = set()
    articles: list[SitemapArticleUrl] = []
    while queue and len(articles) < limit:
        sitemap_url = queue.popleft()
        if sitemap_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sitemap_url)

        response = await fetcher.fetch(sitemap_url)
        if not response.ok:
            continue
        nested_sitemaps, urls = parse_sitemap(response.content, sitemap_url=sitemap_url)
        matching_nested_sitemaps = [
            nested
            for nested in nested_sitemaps
            if _matches_any(nested, source.sitemap_url_patterns)
            and _sitemap_url_may_overlap_window(nested, since=since, until=until)
        ]
        for nested in sorted(
            matching_nested_sitemaps,
            key=_sitemap_url_sort_key,
            reverse=True,
        ):
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
            if len(articles) >= limit:
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

    if json_urls := _parse_json_article_links(html, section_url=section_url):
        return json_urls

    soup = BeautifulSoup(html, "html.parser")
    section_host = urlparse(section_url).netloc
    urls: list[str] = []
    seen: set[str] = set()
    for link in soup.find_all("a", href=True):
        if not isinstance(link, Tag):
            continue
        href = link.get("href")
        href = href.strip() if isinstance(href, str) else href
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


def _parse_json_article_links(content: str, *, section_url: str) -> list[str]:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return []

    section_host = urlparse(section_url).netloc
    urls: list[str] = []
    seen: set[str] = set()
    for value in _iter_json_strings(payload):
        if not value.startswith(("http://", "https://", "/")):
            continue
        url = urljoin(section_url, value).split("#", 1)[0]
        if urlparse(url).netloc != section_host:
            continue
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def _iter_json_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        strings: list[str] = []
        for item in value:
            strings.extend(_iter_json_strings(item))
        return strings
    if isinstance(value, dict):
        strings = []
        for item in value.values():
            strings.extend(_iter_json_strings(item))
        return strings
    return []


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


def _sitemap_url_may_overlap_window(
    sitemap_url: str,
    *,
    since: datetime | None,
    until: datetime | None,
) -> bool:
    if since is None and until is None:
        return True
    year_month = _year_month_from_url(sitemap_url)
    if year_month is None:
        return True

    year, month = year_month
    sitemap_start = datetime(year, month, 1, tzinfo=UTC)
    sitemap_end_year = year + 1 if month == 12 else year
    sitemap_end_month = 1 if month == 12 else month + 1
    sitemap_end = datetime(sitemap_end_year, sitemap_end_month, 1, tzinfo=UTC)
    since = _as_utc(since) if since else None
    until = _as_utc(until) if until else None
    if until and sitemap_start > until:
        return False
    return not (since and sitemap_end <= since)


def _sitemap_url_sort_key(sitemap_url: str) -> tuple[int, int, str]:
    year_month = _year_month_from_url(sitemap_url)
    if year_month is None:
        return (0, 0, sitemap_url)
    year, month = year_month
    return (year, month, sitemap_url)


def _year_month_from_url(sitemap_url: str) -> tuple[int, int] | None:
    patterns = (
        r"(?P<year>20\d{2})[/-](?P<month>0?[1-9]|1[0-2])",
        r"(?P<year>20\d{2})-(?P<month>0?[1-9]|1[0-2])",
    )
    for pattern in patterns:
        match = re.search(pattern, sitemap_url)
        if match:
            return int(match.group("year")), int(match.group("month"))
    return None


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
