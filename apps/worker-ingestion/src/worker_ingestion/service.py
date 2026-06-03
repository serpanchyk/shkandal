"""Ingestion orchestration."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from worker_ingestion.config import IngestionConfig
from worker_ingestion.extractor import extract_article
from worker_ingestion.identity import normalize_article_url
from worker_ingestion.sitemap import (
    SitemapArticleUrl,
    discover_article_urls,
    effective_discovery_limit,
)
from worker_ingestion.sources import CURATED_SOURCES, SourceConfig
from worker_ingestion.storage import ArticleInput, ArticleRepository, SourceInput
from worker_ingestion.transport import Fetcher


@dataclass(frozen=True)
class IngestionStats:
    processed_sources: int = 0
    discovered_articles: int = 0
    skipped_existing_articles: int = 0
    stored_articles: int = 0
    failed_articles: int = 0


class IngestionWorker:
    def __init__(
        self,
        *,
        config: IngestionConfig,
        fetcher: Fetcher,
        repository: ArticleRepository,
        sources: tuple[SourceConfig, ...] = CURATED_SOURCES,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config = config
        self.fetcher = fetcher
        self.repository = repository
        self.sources = sources
        self.logger = logger or logging.getLogger(config.service_name)

    async def run_once(
        self,
        *,
        source_slug: str | None = None,
        limit: int | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> IngestionStats:
        selected_sources = self._selected_sources(source_slug)
        stats = IngestionStats()
        for source in selected_sources:
            source_stats = await self._run_source(source, limit=limit, since=since, until=until)
            stats = IngestionStats(
                processed_sources=stats.processed_sources + 1,
                discovered_articles=stats.discovered_articles + source_stats.discovered_articles,
                skipped_existing_articles=(
                    stats.skipped_existing_articles + source_stats.skipped_existing_articles
                ),
                stored_articles=stats.stored_articles + source_stats.stored_articles,
                failed_articles=stats.failed_articles + source_stats.failed_articles,
            )
        return stats

    async def _run_source(
        self,
        source: SourceConfig,
        *,
        limit: int | None,
        since: datetime | None,
        until: datetime | None,
    ) -> IngestionStats:
        self.logger.info(
            "worker_ingestion_source_started",
            extra={"source_slug": source.slug, "source_type": source.source_type},
        )
        source_id = await self.repository.ensure_source(
            SourceInput(
                slug=source.slug,
                name=source.name,
                source_type=source.source_type,
                base_url=source.base_url,
                language=source.language,
                metadata=source.metadata,
            )
        )
        urls = await discover_article_urls(
            source,
            self.fetcher,
            self.config,
            since=since,
            until=until,
        )
        discovery_limit = effective_discovery_limit(self.config, since=since, until=until)
        self.logger.info(
            "worker_ingestion_source_discovered",
            extra={
                "source_slug": source.slug,
                "discovered_articles": len(urls),
                "discovery_limit": discovery_limit,
            },
        )
        if limit is not None:
            urls = urls[:limit]

        discovered_articles = len(urls)
        existing_identity_urls = await self.repository.existing_identity_urls(
            {normalize_article_url(article_url.url) for article_url in urls}
        )
        if existing_identity_urls:
            urls = [
                article_url
                for article_url in urls
                if normalize_article_url(article_url.url) not in existing_identity_urls
            ]
            self.logger.info(
                "worker_ingestion_source_existing_articles_skipped",
                extra={
                    "source_slug": source.slug,
                    "skipped_existing_articles": discovered_articles - len(urls),
                    "remaining_articles": len(urls),
                },
            )

        request_concurrency = (
            1 if source.crawl_delay_seconds is not None else self.config.request_concurrency
        )
        semaphore = asyncio.Semaphore(request_concurrency)
        results = await asyncio.gather(
            *(
                self._ingest_article(source, source_id, article_url, semaphore)
                for article_url in urls
            )
        )
        stored_articles = sum(1 for result in results if result)
        stats = IngestionStats(
            processed_sources=1,
            discovered_articles=discovered_articles,
            skipped_existing_articles=discovered_articles - len(urls),
            stored_articles=stored_articles,
            failed_articles=len(urls) - stored_articles,
        )
        self.logger.info(
            "worker_ingestion_source_finished",
            extra={
                "source_slug": source.slug,
                "discovered_articles": stats.discovered_articles,
                "skipped_existing_articles": stats.skipped_existing_articles,
                "stored_articles": stats.stored_articles,
                "failed_articles": stats.failed_articles,
            },
        )
        return stats

    async def _ingest_article(
        self,
        source: SourceConfig,
        source_id: UUID,
        article_url: SitemapArticleUrl,
        semaphore: asyncio.Semaphore,
    ) -> bool:
        async with semaphore:
            if source.crawl_delay_seconds is not None:
                await asyncio.sleep(source.crawl_delay_seconds)
            response = await self.fetcher.fetch(article_url.url)
        if not response.ok:
            self.logger.warning(
                "worker_ingestion_article_fetch_failed",
                extra={
                    "source_slug": source.slug,
                    "article_url": article_url.url,
                    "status_code": response.status_code,
                    "fetch_error": response.error or "non_2xx_response",
                    "content_type": response.headers.get("content-type"),
                    "discovery_method": article_url.discovery_method,
                    "discovery_url": article_url.discovery_url,
                },
            )
            await self.repository.upsert_article(
                ArticleInput(
                    source_id=source_id,
                    url=article_url.url,
                    identity_url=normalize_article_url(article_url.url),
                    title=None,
                    lead=None,
                    published_at=None,
                    fetched_at=response.fetched_at,
                    source_language=source.language,
                    raw_html=None,
                    extracted_text=None,
                    remote_image_url=None,
                    remote_image_metadata={},
                    source_metadata={
                        "discovery_url": article_url.discovery_url,
                        "discovery_method": article_url.discovery_method,
                        "discovery_lastmod": article_url.lastmod.isoformat()
                        if article_url.lastmod
                        else None,
                        "sitemap_url": article_url.sitemap_url,
                        "sitemap_lastmod": article_url.lastmod.isoformat()
                        if article_url.lastmod and article_url.discovery_method == "sitemap"
                        else None,
                        "http_status": response.status_code,
                        "content_type": response.headers.get("content-type"),
                        "fetch_error": response.error or "non_2xx_response",
                    },
                )
            )
            return False

        extracted = extract_article(source, url=article_url.url, html=response.text)
        await self.repository.upsert_article(
            ArticleInput(
                source_id=source_id,
                url=article_url.url,
                identity_url=extracted.identity_url,
                title=extracted.title,
                lead=extracted.lead,
                published_at=extracted.published_at,
                fetched_at=response.fetched_at,
                source_language=extracted.source_language,
                raw_html=response.text,
                extracted_text=extracted.extracted_text,
                remote_image_url=extracted.remote_image_url,
                remote_image_metadata={},
                source_metadata={
                    "author": extracted.author,
                    "discovery_url": article_url.discovery_url,
                    "discovery_method": article_url.discovery_method,
                    "discovery_lastmod": article_url.lastmod.isoformat()
                    if article_url.lastmod
                    else None,
                    "sitemap_url": article_url.sitemap_url,
                    "sitemap_lastmod": article_url.lastmod.isoformat()
                    if article_url.lastmod and article_url.discovery_method == "sitemap"
                    else None,
                    "http_status": response.status_code,
                    "content_type": response.headers.get("content-type"),
                },
            )
        )
        return True

    def _selected_sources(self, source_slug: str | None) -> tuple[SourceConfig, ...]:
        if source_slug is None:
            return self.sources
        return tuple(source for source in self.sources if source.slug == source_slug)
