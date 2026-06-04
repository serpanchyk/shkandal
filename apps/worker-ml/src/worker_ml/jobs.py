"""ML worker job enqueueing."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from shkandal_database.jobs import ArticleJobStore
from shkandal_database.models import Article, ArticleRelevance
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

CLASSIFY_ARTICLE_JOB = "classify_article"


@dataclass(frozen=True)
class EnqueueStats:
    """Counts from one ML job enqueue pass."""

    scanned_articles: int
    ensured_jobs: int


class MlJobPlanner:
    """Find missing ML work and enqueue durable article jobs."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        job_store: ArticleJobStore,
    ) -> None:
        self._session_factory = session_factory
        self._job_store = job_store

    async def enqueue_missing_classification_jobs(
        self,
        *,
        limit: int,
        max_attempts: int,
    ) -> EnqueueStats:
        """Create one classify job for each article missing classifier output."""

        async with self._session_factory() as session:
            article_ids = list(
                (
                    await session.scalars(
                        self._articles_missing_relevance_query(limit=limit),
                    )
                ).all()
            )

        for article_id in article_ids:
            await self._job_store.enqueue_article_job(
                job_type=CLASSIFY_ARTICLE_JOB,
                article_id=article_id,
                payload={"article_id": str(article_id)},
                max_attempts=max_attempts,
            )

        return EnqueueStats(scanned_articles=len(article_ids), ensured_jobs=len(article_ids))

    @staticmethod
    def _articles_missing_relevance_query(*, limit: int) -> Select[tuple[UUID]]:
        return (
            select(Article.id)
            .outerjoin(ArticleRelevance, ArticleRelevance.article_id == Article.id)
            .where(ArticleRelevance.id.is_(None))
            .order_by(Article.published_at.asc().nulls_last(), Article.created_at.asc())
            .limit(limit)
        )
