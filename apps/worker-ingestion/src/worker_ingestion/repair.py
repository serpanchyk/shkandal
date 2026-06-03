"""Repair helpers for stored article records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from worker_ingestion.extractor import published_at_from_html
from worker_ingestion.storage import PublishedAtRepairRow


class PublishedAtRepairRepository(Protocol):
    async def iter_articles_missing_published_at(
        self,
        *,
        source_slug: str | None,
        limit: int | None,
        batch_size: int,
    ) -> list[PublishedAtRepairRow]:
        """Return stored articles that can be repaired from raw HTML."""

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

    rows = await repository.iter_articles_missing_published_at(
        source_slug=source_slug,
        limit=limit,
        batch_size=batch_size,
    )
    repairable_articles = 0
    updated_articles = 0
    for row in rows:
        published_at = published_at_from_html(row.raw_html)
        if published_at is None:
            continue
        repairable_articles += 1
        if apply:
            await repository.update_article_published_at(row.article_id, published_at)
            updated_articles += 1

    return PublishedAtRepairStats(
        scanned_articles=len(rows),
        repairable_articles=repairable_articles,
        updated_articles=updated_articles,
    )
