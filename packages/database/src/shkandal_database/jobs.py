"""PostgreSQL-backed article job store."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from random import SystemRandom
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import Select, and_, case, desc, func, or_, select, update
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
    article_id: UUID | None
    payload: dict[str, Any]
    attempt_count: int
    max_attempts: int
    case_id: UUID | None = None
    requested_revision: int = 1


@dataclass(frozen=True)
class EnqueueJobResult:
    """Result of ensuring one durable article job exists."""

    job_id: UUID
    state: Literal["inserted", "existing", "requeued"]


@dataclass(frozen=True)
class BulkEnqueueJobResult:
    """Counts from ensuring a batch of article jobs exists."""

    inserted_jobs: int
    requeued_jobs: int
    existing_jobs: int


@dataclass(frozen=True)
class JobQueueSummary:
    """Current durable job counts for a selected set of job types."""

    queued_jobs: int
    running_jobs: int
    blocked_jobs: int
    failed_jobs: int
    next_run_after: datetime | None
    blocked_running_jobs: int = 0


class ArticleJobStore:
    """Store and claim durable typed-subject jobs."""

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
        requeue_failed: bool = True,
    ) -> EnqueueJobResult:
        """Create an article job or requeue an existing failed job."""

        return await self._enqueue_job(
            job_type=job_type,
            subject_column=Job.article_id,
            subject_id=article_id,
            values={"article_id": article_id},
            payload=payload,
            priority=priority,
            run_after=run_after,
            max_attempts=max_attempts,
            increment_revision=False,
            requeue_failed=requeue_failed,
        )

    async def enqueue_article_jobs(
        self,
        *,
        job_type: str,
        article_ids: list[UUID],
        max_attempts: int = 3,
        requeue_failed: bool = True,
    ) -> BulkEnqueueJobResult:
        """Ensure many article jobs in one transaction."""

        if not article_ids:
            return BulkEnqueueJobResult(0, 0, 0)

        async with async_session_scope(self._session_factory) as session:
            inserted = [
                article_id
                for article_id in (
                    await session.scalars(
                        insert(Job)
                        .values(
                            [
                                {
                                    "job_type": job_type,
                                    "article_id": article_id,
                                    "status": JOB_STATUS_QUEUED,
                                    "payload": {"article_id": str(article_id)},
                                    "max_attempts": max_attempts,
                                }
                                for article_id in article_ids
                            ]
                        )
                        .on_conflict_do_nothing(
                            index_elements=[Job.job_type, Job.article_id],
                            index_where=Job.article_id.is_not(None),
                        )
                        .returning(Job.article_id)
                    )
                ).all()
                if article_id is not None
            ]
            requeued: list[UUID] = []
            if requeue_failed:
                requeued = [
                    article_id
                    for article_id in (
                        await session.scalars(
                            update(Job)
                            .where(
                                Job.job_type == job_type,
                                Job.article_id.in_(article_ids),
                                Job.status == JOB_STATUS_FAILED,
                            )
                            .values(
                                status=JOB_STATUS_QUEUED,
                                attempt_count=0,
                                run_after=None,
                                locked_at=None,
                                locked_by=None,
                                last_error=None,
                                max_attempts=max_attempts,
                                updated_at=datetime.now(UTC),
                            )
                            .returning(Job.article_id)
                        )
                    ).all()
                    if article_id is not None
                ]

        return BulkEnqueueJobResult(
            inserted_jobs=len(inserted),
            requeued_jobs=len(requeued),
            existing_jobs=len(article_ids) - len(inserted) - len(requeued),
        )

    async def enqueue_case_job(
        self,
        *,
        job_type: str,
        case_id: UUID,
        payload: dict[str, Any] | None = None,
        priority: int = 0,
        run_after: datetime | None = None,
        max_attempts: int = 3,
    ) -> EnqueueJobResult:
        """Create or request another revision of one case-scoped job."""

        return await self._enqueue_job(
            job_type=job_type,
            subject_column=Job.case_id,
            subject_id=case_id,
            values={"case_id": case_id},
            payload=payload,
            priority=priority,
            run_after=run_after,
            max_attempts=max_attempts,
            increment_revision=True,
            requeue_failed=True,
        )

    async def ensure_case_job(
        self,
        *,
        job_type: str,
        case_id: UUID,
        payload: dict[str, Any] | None = None,
        priority: int = 0,
        run_after: datetime | None = None,
        max_attempts: int = 3,
        requeue_failed: bool = True,
    ) -> EnqueueJobResult:
        """Ensure a recurring Case job exists without requesting a new revision."""

        return await self._enqueue_job(
            job_type=job_type,
            subject_column=Job.case_id,
            subject_id=case_id,
            values={"case_id": case_id},
            payload=payload,
            priority=priority,
            run_after=run_after,
            max_attempts=max_attempts,
            increment_revision=False,
            requeue_failed=requeue_failed,
            requeue_succeeded=True,
        )

    async def _enqueue_job(
        self,
        *,
        job_type: str,
        subject_column: Any,
        subject_id: UUID,
        values: dict[str, UUID],
        payload: dict[str, Any] | None,
        priority: int,
        run_after: datetime | None,
        max_attempts: int,
        increment_revision: bool,
        requeue_failed: bool,
        requeue_succeeded: bool = False,
    ) -> EnqueueJobResult:
        async with async_session_scope(self._session_factory) as session:
            statement = (
                insert(Job)
                .values(
                    job_type=job_type,
                    **values,
                    status=JOB_STATUS_QUEUED,
                    priority=priority,
                    payload=payload or {},
                    run_after=run_after,
                    max_attempts=max_attempts,
                )
                .on_conflict_do_nothing(
                    index_elements=[Job.job_type, subject_column],
                    index_where=subject_column.is_not(None),
                )
                .returning(Job.id)
            )
            inserted_id = await session.scalar(statement)
            if inserted_id is not None:
                return EnqueueJobResult(job_id=inserted_id, state="inserted")

            existing_job = (
                await session.execute(
                    select(Job.id, Job.status)
                    .where(Job.job_type == job_type, subject_column == subject_id)
                    .with_for_update()
                )
            ).one_or_none()
            if existing_job is None:
                raise RuntimeError("job insert conflicted but existing job was not found")
            if increment_revision:
                next_status = (
                    existing_job.status
                    if existing_job.status in {JOB_STATUS_RUNNING, JOB_STATUS_QUEUED}
                    else JOB_STATUS_QUEUED
                )
                update_values: dict[str, Any] = {
                    "requested_revision": Job.requested_revision + 1,
                    "status": next_status,
                    "run_after": run_after,
                    "last_error": None,
                }
                if existing_job.status != JOB_STATUS_RUNNING:
                    update_values.update(
                        attempt_count=0,
                        locked_at=None,
                        locked_by=None,
                    )
                if payload is not None:
                    update_values["payload"] = payload
                await session.execute(
                    update(Job).where(Job.id == existing_job.id).values(**update_values)
                )
                return EnqueueJobResult(job_id=existing_job.id, state="requeued")
            if existing_job.status == JOB_STATUS_SUCCEEDED and requeue_succeeded:
                requeued_id = await session.scalar(
                    update(Job)
                    .where(Job.id == existing_job.id, Job.status == JOB_STATUS_SUCCEEDED)
                    .values(
                        status=JOB_STATUS_QUEUED,
                        attempt_count=0,
                        run_after=run_after,
                        locked_at=None,
                        locked_by=None,
                        last_error=None,
                        max_attempts=max_attempts,
                        updated_at=datetime.now(UTC),
                    )
                    .returning(Job.id)
                )
                return EnqueueJobResult(
                    job_id=requeued_id or existing_job.id,
                    state="requeued" if requeued_id is not None else "existing",
                )
            if existing_job.status != JOB_STATUS_FAILED:
                return EnqueueJobResult(job_id=existing_job.id, state="existing")
            if not requeue_failed:
                return EnqueueJobResult(job_id=existing_job.id, state="existing")

            requeued_at = datetime.now(UTC)
            requeued_id = await session.scalar(
                update(Job)
                .where(Job.id == existing_job.id, Job.status == JOB_STATUS_FAILED)
                .values(
                    status=JOB_STATUS_QUEUED,
                    attempt_count=0,
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

    async def summarize_jobs(self, *, job_types: tuple[str, ...]) -> JobQueueSummary:
        """Return queue state for the selected job types."""

        stale_before = datetime.now(UTC) - self._stale_job_timeout
        processable_queued = and_(
            Job.status == JOB_STATUS_QUEUED,
            Job.attempt_count < Job.max_attempts,
        )
        blocked_running = and_(
            Job.status == JOB_STATUS_RUNNING,
            Job.locked_at < stale_before,
            Job.attempt_count >= Job.max_attempts,
        )
        blocked_queued = and_(
            Job.status == JOB_STATUS_QUEUED,
            Job.attempt_count >= Job.max_attempts,
        )
        blocked = or_(blocked_running, blocked_queued)
        statement = select(
            func.count().filter(processable_queued),
            func.count().filter(Job.status == JOB_STATUS_RUNNING),
            func.count().filter(blocked),
            func.count().filter(Job.status == JOB_STATUS_FAILED),
            func.min(Job.run_after).filter(processable_queued),
            func.count().filter(blocked_running),
        ).where(Job.job_type.in_(job_types))
        async with self._session_factory() as session:
            row = (await session.execute(statement)).one()
        return JobQueueSummary(
            queued_jobs=row[0],
            running_jobs=row[1],
            blocked_jobs=row[2],
            failed_jobs=row[3],
            next_run_after=row[4],
            blocked_running_jobs=row[5],
        )

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
                    Job.case_id,
                    Job.payload,
                    Job.attempt_count,
                    Job.max_attempts,
                    Job.requested_revision,
                )
            )
            row = (await session.execute(statement)).one()
            return ClaimedJob(
                id=row.id,
                job_type=row.job_type,
                article_id=row.article_id,
                case_id=row.case_id,
                payload=row.payload,
                attempt_count=row.attempt_count,
                max_attempts=row.max_attempts,
                requested_revision=row.requested_revision,
            )

    async def complete_job(
        self,
        *,
        job_id: UUID,
        processed_revision: int | None = None,
        now: datetime | None = None,
    ) -> None:
        """Mark a claimed job as succeeded."""

        finished_at = now or datetime.now(UTC)
        async with async_session_scope(self._session_factory) as session:
            if processed_revision is None:
                await session.execute(
                    update(Job)
                    .where(Job.id == job_id)
                    .values(
                        status=JOB_STATUS_SUCCEEDED,
                        completed_revision=Job.requested_revision,
                        locked_at=None,
                        locked_by=None,
                        last_error=None,
                        updated_at=finished_at,
                    )
                )
                return
            await session.execute(
                update(Job)
                .where(Job.id == job_id)
                .values(
                    status=case(
                        (Job.requested_revision > processed_revision, JOB_STATUS_QUEUED),
                        else_=JOB_STATUS_SUCCEEDED,
                    ),
                    completed_revision=processed_revision,
                    run_after=case(
                        (Job.requested_revision > processed_revision, finished_at),
                        else_=Job.run_after,
                    ),
                    attempt_count=case(
                        (Job.requested_revision > processed_revision, 0),
                        else_=Job.attempt_count,
                    ),
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
        processed_revision: int | None = None,
        now: datetime | None = None,
    ) -> None:
        """Record job failure and either retry or exhaust the job."""

        failed_at = now or datetime.now(UTC)
        exhausted = attempt_count >= max_attempts
        status: Any = JOB_STATUS_FAILED if exhausted else JOB_STATUS_QUEUED
        stored_attempt_count: Any = Job.attempt_count
        if processed_revision is not None:
            newer_revision = Job.requested_revision > processed_revision
            status = case((newer_revision, JOB_STATUS_QUEUED), else_=status)
            stored_attempt_count = case((newer_revision, 0), else_=Job.attempt_count)
        values: dict[str, Any] = {
            "status": status,
            "attempt_count": stored_attempt_count,
            "locked_at": None,
            "locked_by": None,
            "last_error": error_message,
            "updated_at": failed_at,
        }
        retry_at = failed_at + self.retry_delay(attempt_count)
        if processed_revision is not None:
            values["run_after"] = case(
                (Job.requested_revision > processed_revision, failed_at),
                else_=retry_at if not exhausted else Job.run_after,
            )
        elif not exhausted:
            values["run_after"] = retry_at

        async with async_session_scope(self._session_factory) as session:
            await session.execute(update(Job).where(Job.id == job_id).values(**values))

    async def defer_job(
        self,
        *,
        job_id: UUID,
        run_after: datetime,
        reason: str,
        now: datetime | None = None,
    ) -> None:
        """Release a claimed job without consuming its attempt."""

        deferred_at = now or datetime.now(UTC)
        async with async_session_scope(self._session_factory) as session:
            await session.execute(
                update(Job)
                .where(Job.id == job_id, Job.status == JOB_STATUS_RUNNING)
                .values(
                    status=JOB_STATUS_QUEUED,
                    attempt_count=Job.attempt_count - 1,
                    run_after=run_after,
                    locked_at=None,
                    locked_by=None,
                    last_error=reason,
                    updated_at=deferred_at,
                )
            )

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
            Job.attempt_count < Job.max_attempts,
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
