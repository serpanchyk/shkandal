"""ML worker job enqueueing."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from shkandal_database.jobs import ArticleJobStore
from shkandal_database.models import Article, ArticleRelevance, Case
from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

CLASSIFY_ARTICLE_JOB = "classify_article"
CREATE_ARTICLE_CARD_JOB = "create_article_card"
RESOLVE_ARTICLE_CASES_JOB = "resolve_article_cases"
RESOLVE_ARTICLE_ENTITIES_JOB = "resolve_article_entities"
RESOLVE_ARTICLE_EVENTS_JOB = "resolve_article_events"
UPDATE_CASE_COPY_JOB = "update_case_copy"
AUDIT_CASE_COHERENCE_JOB = "audit_case_coherence"


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

        result = await self._job_store.enqueue_article_jobs(
            job_type=CLASSIFY_ARTICLE_JOB,
            article_ids=article_ids,
            max_attempts=max_attempts,
            requeue_failed=requeue_failed,
        )

        return EnqueueStats(
            scanned_articles=len(article_ids),
            ensured_jobs=result.inserted_jobs + result.requeued_jobs,
            inserted_jobs=result.inserted_jobs,
            requeued_jobs=result.requeued_jobs,
            existing_jobs=result.existing_jobs,
        )

    async def enqueue_due_case_audit_jobs(
        self,
        *,
        limit: int,
        max_attempts: int,
        interval_days: int,
    ) -> EnqueueStats:
        """Enqueue active Cases with changed or stale audited evidence."""

        from datetime import UTC, datetime, timedelta

        cutoff = datetime.now(UTC) - timedelta(days=interval_days)
        async with self._session_factory() as session:
            case_ids = list(
                (
                    await session.scalars(
                        select(Case.id)
                        .where(
                            Case.status == "active",
                            or_(
                                Case.last_audited_revision < Case.evidence_revision,
                                Case.last_audited_at.is_(None),
                                Case.last_audited_at <= cutoff,
                            ),
                        )
                        .order_by(Case.last_audited_at.asc().nulls_first(), Case.created_at.asc())
                        .limit(limit)
                    )
                ).all()
            )
        states = [
            await self._job_store.ensure_case_job(
                job_type=AUDIT_CASE_COHERENCE_JOB,
                case_id=case_id,
                payload={"case_id": str(case_id)},
                max_attempts=max_attempts,
            )
            for case_id in case_ids
        ]
        inserted = sum(result.state == "inserted" for result in states)
        requeued = sum(result.state == "requeued" for result in states)
        return EnqueueStats(
            scanned_articles=len(case_ids),
            ensured_jobs=inserted + requeued,
            inserted_jobs=inserted,
            requeued_jobs=requeued,
            existing_jobs=len(states) - inserted - requeued,
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
