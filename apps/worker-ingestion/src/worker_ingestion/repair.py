"""Repair helpers for stored article records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from worker_ingestion.extractor import published_at_from_html
from worker_ingestion.storage import PublishedAtRepairRow


class PublishedAtRepairRepository(Protocol):
    async def fetch_articles_missing_published_at_batch(
        self,
        *,
        source_slug: str | None,
        limit: int | None,
        after_created_at: datetime | None,
        after_article_id: UUID | None,
    ) -> list[PublishedAtRepairRow]:
        """Return one bounded page of stored articles repairable from raw HTML."""

    async def update_article_published_at(self, article_id: UUID, published_at: datetime) -> None:
        """Persist one repaired publication datetime."""


@dataclass(frozen=True)
class PublishedAtRepairStats:
    scanned_articles: int = 0
    repairable_articles: int = 0
    updated_articles: int = 0


async def repair_missing_published_at(
    repository: PublishedAtRepairRepository,
    *,
    apply: bool = False,
    source_slug: str | None = None,
    limit: int | None = None,
    batch_size: int = 500,
) -> PublishedAtRepairStats:
    """Repair missing article publication dates from stored raw HTML."""

    if batch_size < 1:
        raise ValueError("batch_size must be greater than zero")

    scanned_articles = 0
    repairable_articles = 0
    updated_articles = 0
    after_created_at: datetime | None = None
    after_article_id: UUID | None = None

    while limit is None or scanned_articles < limit:
        remaining_limit = None if limit is None else limit - scanned_articles
        page_limit = batch_size if remaining_limit is None else min(batch_size, remaining_limit)
        rows = await repository.fetch_articles_missing_published_at_batch(
            source_slug=source_slug,
            limit=page_limit,
            after_created_at=after_created_at,
            after_article_id=after_article_id,
        )
        if not rows:
            break

        scanned_articles += len(rows)
        last_row = rows[-1]
        after_created_at = last_row.created_at
        after_article_id = last_row.article_id

        for row in rows:
            published_at = published_at_from_html(row.raw_html)
            if published_at is None:
                continue
            repairable_articles += 1
            if apply:
                await repository.update_article_published_at(row.article_id, published_at)
                updated_articles += 1

    return PublishedAtRepairStats(
        scanned_articles=scanned_articles,
        repairable_articles=repairable_articles,
        updated_articles=updated_articles,
    )
