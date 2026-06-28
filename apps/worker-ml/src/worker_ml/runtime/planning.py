"""ML worker job enqueueing."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from shkandal_database.jobs import JOB_STATUS_SUCCEEDED, ArticleJobStore
from shkandal_database.models import (
    Article,
    ArticleCard,
    ArticleGateDecision,
    ArticleRelevance,
    Case,
    CaseCoherenceAudit,
    CasePublicInterestAudit,
    Job,
)
from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

CLASSIFY_ARTICLE_JOB = "classify_article"
GATE_ARTICLE_JOB = "gate_article"
CREATE_ARTICLE_CARD_JOB = "create_article_card"
RESOLVE_ARTICLE_CASES_JOB = "resolve_article_cases"
RESOLVE_ARTICLE_ENTITIES_JOB = "resolve_article_entities"
RESOLVE_ARTICLE_EVENTS_JOB = "resolve_article_events"
REFRESH_CASE_JOB = "refresh_case"
AUDIT_CASE_COHERENCE_JOB = "audit_case_coherence"
AUDIT_CASE_PUBLIC_INTEREST_JOB = "audit_case_public_interest"
AUDIT_CASE_DUPLICATES_JOB = "audit_case_duplicates"

SUPPORTED_JOB_TYPES = (
    CLASSIFY_ARTICLE_JOB,
    GATE_ARTICLE_JOB,
    CREATE_ARTICLE_CARD_JOB,
    RESOLVE_ARTICLE_CASES_JOB,
    RESOLVE_ARTICLE_ENTITIES_JOB,
    RESOLVE_ARTICLE_EVENTS_JOB,
    REFRESH_CASE_JOB,
    AUDIT_CASE_COHERENCE_JOB,
    AUDIT_CASE_PUBLIC_INTEREST_JOB,
    AUDIT_CASE_DUPLICATES_JOB,
)
JOB_TYPE_SCHEDULE = (
    GATE_ARTICLE_JOB,
    CREATE_ARTICLE_CARD_JOB,
    REFRESH_CASE_JOB,
    AUDIT_CASE_COHERENCE_JOB,
    AUDIT_CASE_PUBLIC_INTEREST_JOB,
    AUDIT_CASE_DUPLICATES_JOB,
    RESOLVE_ARTICLE_CASES_JOB,
    RESOLVE_ARTICLE_ENTITIES_JOB,
    RESOLVE_ARTICLE_EVENTS_JOB,
    CLASSIFY_ARTICLE_JOB,
)


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

    async def enqueue_missing_article_card_jobs(
        self,
        *,
        limit: int,
        max_attempts: int,
        requeue_failed: bool = True,
    ) -> EnqueueStats:
        """Create one article-card job for each accepted gate missing a card."""

        async with self._session_factory() as session:
            article_ids = list(
                (
                    await session.scalars(
                        self._articles_missing_card_query(limit=limit),
                    )
                ).all()
            )

        result = await self._job_store.enqueue_article_jobs(
            job_type=CREATE_ARTICLE_CARD_JOB,
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

    async def enqueue_missing_article_gate_jobs(
        self,
        *,
        limit: int,
        max_attempts: int,
        requeue_failed: bool = True,
    ) -> EnqueueStats:
        """Create one gate job for each classifier-relevant article missing a gate."""

        async with self._session_factory() as session:
            article_ids = list(
                (
                    await session.scalars(
                        self._articles_missing_gate_query(limit=limit),
                    )
                ).all()
            )

        result = await self._job_store.enqueue_article_jobs(
            job_type=GATE_ARTICLE_JOB,
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

    async def enqueue_due_case_refresh_jobs(
        self,
        *,
        limit: int,
        max_attempts: int,
    ) -> EnqueueStats:
        """Enqueue active Cases that need reader-facing refresh."""

        async with self._session_factory() as session:
            case_ids = list(
                (
                    await session.scalars(
                        self._cases_due_for_refresh_query(limit=limit),
                    )
                ).all()
            )
        states = [
            await self._job_store.ensure_case_job(
                job_type=REFRESH_CASE_JOB,
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

    async def enqueue_coherent_successful_case_audit_reruns(
        self,
        *,
        limit: int | None,
        max_attempts: int,
    ) -> EnqueueStats:
        """Request fresh audit revisions for latest coherent successful audits."""

        async with self._session_factory() as session:
            case_ids = list(
                (
                    await session.scalars(
                        self._coherent_successful_case_audit_rerun_query(limit=limit)
                    )
                ).all()
            )
        states = [
            await self._job_store.enqueue_case_job(
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

    async def enqueue_active_case_public_interest_reruns(
        self,
        *,
        limit: int | None,
        max_attempts: int,
    ) -> EnqueueStats:
        """Request fresh public-interest audit revisions for active Cases."""

        async with self._session_factory() as session:
            case_ids = list(
                (
                    await session.scalars(
                        self._active_case_public_interest_rerun_query(limit=limit)
                    )
                ).all()
            )
        states = [
            await self._job_store.enqueue_case_job(
                job_type=AUDIT_CASE_PUBLIC_INTEREST_JOB,
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
    def _coherent_successful_case_audit_rerun_query(
        *,
        limit: int | None,
    ) -> Select[tuple[UUID]]:
        latest_audit_id = (
            select(CaseCoherenceAudit.id)
            .where(CaseCoherenceAudit.case_id == Case.id)
            .order_by(CaseCoherenceAudit.created_at.desc(), CaseCoherenceAudit.id.desc())
            .limit(1)
            .correlate(Case)
            .scalar_subquery()
        )
        query = (
            select(Case.id)
            .join(
                Job,
                (Job.case_id == Case.id) & (Job.job_type == AUDIT_CASE_COHERENCE_JOB),
            )
            .join(CaseCoherenceAudit, CaseCoherenceAudit.id == latest_audit_id)
            .where(
                Case.status == "active",
                Job.status == JOB_STATUS_SUCCEEDED,
                CaseCoherenceAudit.outcome == "coherent",
            )
            .order_by(CaseCoherenceAudit.created_at.asc(), Case.created_at.asc())
        )
        return query.limit(limit) if limit is not None else query

    @staticmethod
    def _active_case_public_interest_rerun_query(
        *,
        limit: int | None,
    ) -> Select[tuple[UUID]]:
        latest_audit_id = (
            select(CasePublicInterestAudit.id)
            .where(CasePublicInterestAudit.case_id == Case.id)
            .order_by(CasePublicInterestAudit.created_at.desc(), CasePublicInterestAudit.id.desc())
            .limit(1)
            .correlate(Case)
            .scalar_subquery()
        )
        query = (
            select(Case.id)
            .outerjoin(CasePublicInterestAudit, CasePublicInterestAudit.id == latest_audit_id)
            .where(Case.status == "active")
            .order_by(
                CasePublicInterestAudit.created_at.asc().nulls_first(),
                Case.last_interest_audited_at.asc().nulls_first(),
                Case.created_at.asc(),
            )
        )
        return query.limit(limit) if limit is not None else query

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

    @staticmethod
    def _articles_missing_card_query(*, limit: int) -> Select[tuple[UUID]]:
        return (
            select(Article.id)
            .join(ArticleGateDecision, ArticleGateDecision.article_id == Article.id)
            .outerjoin(ArticleCard, ArticleCard.article_id == Article.id)
            .where(
                ArticleGateDecision.is_case_candidate.is_(True),
                ArticleCard.id.is_(None),
            )
            .order_by(Article.published_at.asc().nulls_last(), Article.created_at.asc())
            .limit(limit)
        )

    @staticmethod
    def _articles_missing_gate_query(*, limit: int) -> Select[tuple[UUID]]:
        return (
            select(Article.id)
            .join(ArticleRelevance, ArticleRelevance.article_id == Article.id)
            .outerjoin(ArticleGateDecision, ArticleGateDecision.article_id == Article.id)
            .where(
                ArticleRelevance.is_relevant.is_(True),
                ArticleGateDecision.id.is_(None),
            )
            .order_by(Article.published_at.asc().nulls_last(), Article.created_at.asc())
            .limit(limit)
        )

    @staticmethod
    def _cases_due_for_refresh_query(*, limit: int) -> Select[tuple[UUID]]:
        square_root = func.floor(func.sqrt(Case.article_count))
        missing_public_summary = or_(
            Case.summary_uk.is_(None),
            func.length(func.trim(Case.summary_uk)) == 0,
        )
        due_square_threshold = and_(
            Case.article_count > Case.last_refreshed_article_count,
            Case.article_count > 0,
            square_root * square_root == Case.article_count,
        )
        return (
            select(Case.id)
            .where(
                Case.status == "active",
                or_(missing_public_summary, due_square_threshold),
            )
            .order_by(Case.last_updated_at.asc().nulls_first(), Case.created_at.asc())
            .limit(limit)
        )
