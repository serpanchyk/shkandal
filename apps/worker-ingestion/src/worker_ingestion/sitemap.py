"""Sitemap discovery."""

from __future__ import annotations

import gzip
import re
import xml.etree.ElementTree as ET
from collections import deque
from dataclasses import dataclass
from datetime import datetime

from worker_ingestion.config import IngestionConfig
from worker_ingestion.sources import SourceConfig
from worker_ingestion.transport import Fetcher


@dataclass(frozen=True)
class SitemapArticleUrl:
    url: str
    sitemap_url: str
    lastmod: datetime | None = None


async def discover_article_urls(
    source: SourceConfig,
    fetcher: Fetcher,
    config: IngestionConfig,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[SitemapArticleUrl]:
    """Discover likely article URLs from source sitemaps."""

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
            articles.append(SitemapArticleUrl(url=url, sitemap_url=sitemap_url, lastmod=lastmod))
            if len(articles) >= config.max_sitemap_urls_per_source:
                break

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
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _in_window(
    lastmod: datetime | None,
    *,
    since: datetime | None,
    until: datetime | None,
) -> bool:
    if lastmod is None:
        return True
    if since and lastmod < since:
        return False
    return not (until and lastmod > until)


def _is_allowed_article_url(url: str, source: SourceConfig) -> bool:
    if source.include_url_patterns and not _matches_any(url, source.include_url_patterns):
        return False
    return not _matches_any(url, source.exclude_url_patterns)


def _matches_any(value: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, value) for pattern in patterns)
