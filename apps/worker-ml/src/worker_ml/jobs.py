"""ML worker job enqueueing."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from shkandal_database.jobs import ArticleJobStore
from shkandal_database.models import Article, ArticleRelevance
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

CLASSIFY_ARTICLE_JOB = "classify_article"
CREATE_ARTICLE_CARD_JOB = "create_article_card"
RESOLVE_ARTICLE_CASES_JOB = "resolve_article_cases"
RESOLVE_ARTICLE_ENTITIES_JOB = "resolve_article_entities"
RESOLVE_ARTICLE_EVENTS_JOB = "resolve_article_events"
UPDATE_CASE_COPY_JOB = "update_case_copy"


@dataclass(frozen=True)
class EnqueueStats:
    """Counts from one ML job enqueue pass."""

    scanned_articles: int
    ensured_jobs: int
    inserted_jobs: int = 0
    requeued_jobs: int = 0
    existing_jobs: int = 0


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
        requeue_failed: bool = True,
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

        inserted_jobs = 0
        requeued_jobs = 0
        existing_jobs = 0
        for article_id in article_ids:
            result = await self._job_store.enqueue_article_job(
                job_type=CLASSIFY_ARTICLE_JOB,
                article_id=article_id,
                payload={"article_id": str(article_id)},
                max_attempts=max_attempts,
                requeue_failed=requeue_failed,
            )
            if result.state == "inserted":
                inserted_jobs += 1
            elif result.state == "requeued":
                requeued_jobs += 1
            else:
                existing_jobs += 1

        return EnqueueStats(
            scanned_articles=len(article_ids),
            ensured_jobs=inserted_jobs + requeued_jobs,
            inserted_jobs=inserted_jobs,
            requeued_jobs=requeued_jobs,
            existing_jobs=existing_jobs,
        )

    @staticmethod
    def _articles_missing_relevance_query(*, limit: int) -> Select[tuple[UUID]]:
        return (
            select(Article.id)
            .outerjoin(ArticleRelevance, ArticleRelevance.article_id == Article.id)
            .where(
                ArticleRelevance.id.is_(None),
                Article.fetch_status == "succeeded",
            )
            .order_by(Article.published_at.asc().nulls_last(), Article.created_at.asc())
            .limit(limit)
        )
