"""PostgreSQL-backed article job store."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from random import SystemRandom
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import Select, and_, desc, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from shkandal_database.models import Job
from shkandal_database.session import async_session_scope

JOB_STATUS_QUEUED = "queued"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_SUCCEEDED = "succeeded"
JOB_STATUS_FAILED = "failed"

DEFAULT_RETRY_DELAYS = (
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=15),
)


@dataclass(frozen=True)
class ClaimedJob:
    """A job claimed by one worker for execution."""

    id: UUID
    job_type: str
    article_id: UUID
    payload: dict[str, Any]
    attempt_count: int
    max_attempts: int


@dataclass(frozen=True)
class EnqueueJobResult:
    """Result of ensuring one durable article job exists."""

    job_id: UUID
    state: Literal["inserted", "existing", "requeued"]


class ArticleJobStore:
    """Store and claim durable article-scoped jobs."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        stale_job_timeout: timedelta = timedelta(minutes=30),
        retry_delays: tuple[timedelta, ...] = DEFAULT_RETRY_DELAYS,
        retry_jitter_ratio: float = 0.1,
    ) -> None:
        self._session_factory = session_factory
        self._stale_job_timeout = stale_job_timeout
        self._retry_delays = retry_delays
        self._retry_jitter_ratio = retry_jitter_ratio
        self._random = SystemRandom()

    async def enqueue_article_job(
        self,
        *,
        job_type: str,
        article_id: UUID,
        payload: dict[str, Any] | None = None,
        priority: int = 0,
        run_after: datetime | None = None,
        max_attempts: int = 3,
    ) -> EnqueueJobResult:
        """Create an article job or requeue an existing failed job."""

        async with async_session_scope(self._session_factory) as session:
            statement = (
                insert(Job)
                .values(
                    job_type=job_type,
                    article_id=article_id,
                    status=JOB_STATUS_QUEUED,
                    priority=priority,
                    payload=payload or {},
                    run_after=run_after,
                    max_attempts=max_attempts,
                )
                .on_conflict_do_nothing(
                    index_elements=[Job.job_type, Job.article_id],
                )
                .returning(Job.id)
            )
            inserted_id = await session.scalar(statement)
            if inserted_id is not None:
                return EnqueueJobResult(job_id=inserted_id, state="inserted")

            existing_job = (
                await session.execute(
                    select(Job.id, Job.status)
                    .where(Job.job_type == job_type, Job.article_id == article_id)
                    .with_for_update()
                )
            ).one_or_none()
            if existing_job is None:
                raise RuntimeError("job insert conflicted but existing job was not found")
            if existing_job.status != JOB_STATUS_FAILED:
                return EnqueueJobResult(job_id=existing_job.id, state="existing")

            requeued_at = datetime.now(UTC)
            requeued_id = await session.scalar(
                update(Job)
                .where(Job.id == existing_job.id, Job.status == JOB_STATUS_FAILED)
                .values(
                    status=JOB_STATUS_QUEUED,
                    run_after=run_after,
                    locked_at=None,
                    locked_by=None,
                    last_error=None,
                    max_attempts=max_attempts,
                    updated_at=requeued_at,
                )
                .returning(Job.id)
            )
            if requeued_id is None:
                return EnqueueJobResult(job_id=existing_job.id, state="existing")
            return EnqueueJobResult(job_id=requeued_id, state="requeued")

    async def claim_next_job(
        self,
        *,
        worker_id: str,
        job_types: tuple[str, ...] | None = None,
        now: datetime | None = None,
    ) -> ClaimedJob | None:
        """Claim one eligible queued or stale-running job."""

        claim_time = now or datetime.now(UTC)
        stale_before = claim_time - self._stale_job_timeout

        async with async_session_scope(self._session_factory) as session:
            job_id_query = self._eligible_job_id_query(
                stale_before=stale_before,
                now=claim_time,
                job_types=job_types,
            )
            job_id = await session.scalar(job_id_query.with_for_update(skip_locked=True))
            if job_id is None:
                return None

            statement = (
                update(Job)
                .where(Job.id == job_id)
                .values(
                    status=JOB_STATUS_RUNNING,
                    locked_at=claim_time,
                    locked_by=worker_id,
                    attempt_count=Job.attempt_count + 1,
                    updated_at=claim_time,
                )
                .returning(
                    Job.id,
                    Job.job_type,
                    Job.article_id,
                    Job.payload,
                    Job.attempt_count,
                    Job.max_attempts,
                )
            )
            row = (await session.execute(statement)).one()
            return ClaimedJob(
                id=row.id,
                job_type=row.job_type,
                article_id=row.article_id,
                payload=row.payload,
                attempt_count=row.attempt_count,
                max_attempts=row.max_attempts,
            )

    async def complete_job(self, *, job_id: UUID, now: datetime | None = None) -> None:
        """Mark a claimed job as succeeded."""

        finished_at = now or datetime.now(UTC)
        async with async_session_scope(self._session_factory) as session:
            await session.execute(
                update(Job)
                .where(Job.id == job_id)
                .values(
                    status=JOB_STATUS_SUCCEEDED,
                    locked_at=None,
                    locked_by=None,
                    last_error=None,
                    updated_at=finished_at,
                )
            )

    async def fail_job(
        self,
        *,
        job_id: UUID,
        error_message: str,
        attempt_count: int,
        max_attempts: int,
        now: datetime | None = None,
    ) -> None:
        """Record job failure and either retry or exhaust the job."""

        failed_at = now or datetime.now(UTC)
        exhausted = attempt_count >= max_attempts
        values: dict[str, Any] = {
            "status": JOB_STATUS_FAILED if exhausted else JOB_STATUS_QUEUED,
            "locked_at": None,
            "locked_by": None,
            "last_error": error_message,
            "updated_at": failed_at,
        }
        if not exhausted:
            values["run_after"] = failed_at + self.retry_delay(attempt_count)

        async with async_session_scope(self._session_factory) as session:
            await session.execute(update(Job).where(Job.id == job_id).values(**values))

    def retry_delay(self, attempt_count: int) -> timedelta:
        """Return exponential-ish retry delay for a failed claimed attempt."""

        base_delay = self._retry_delays[min(attempt_count - 1, len(self._retry_delays) - 1)]
        if self._retry_jitter_ratio <= 0:
            return base_delay

        max_jitter_seconds = max(1, int(base_delay.total_seconds() * self._retry_jitter_ratio))
        return base_delay + timedelta(seconds=self._random.randrange(max_jitter_seconds + 1))

    @staticmethod
    def _eligible_job_id_query(
        *,
        stale_before: datetime,
        now: datetime,
        job_types: tuple[str, ...] | None,
    ) -> Select[tuple[UUID]]:
        queued = and_(
            Job.status == JOB_STATUS_QUEUED,
            or_(Job.run_after.is_(None), Job.run_after <= now),
        )
        stale_running = and_(
            Job.status == JOB_STATUS_RUNNING,
            Job.locked_at < stale_before,
            Job.attempt_count < Job.max_attempts,
        )
        statement = (
            select(Job.id)
            .where(or_(queued, stale_running))
            .order_by(desc(Job.priority), Job.run_after.asc().nulls_first(), Job.created_at.asc())
            .limit(1)
        )
        if job_types is not None:
            statement = statement.where(Job.job_type.in_(job_types))
        return statement
