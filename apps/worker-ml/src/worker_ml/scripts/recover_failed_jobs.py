"""Inspect or requeue selected exhausted failed worker jobs."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from shkandal_database.config import DatabaseConfig
from shkandal_database.models import Job
from shkandal_database.session import create_async_engine_from_config, create_async_sessionmaker
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from worker_ml.config import MlConfig


@dataclass(frozen=True)
class FailedJobRecoveryStats:
    """Result of one exhausted-job recovery selection."""

    job_type: str
    selected_job_ids: tuple[UUID, ...]
    applied: bool

    @property
    def selected_jobs(self) -> int:
        """Return the selected exhausted-job count."""

        return len(self.selected_job_ids)


async def recover_failed_jobs(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    job_type: str,
    apply: bool,
    error_contains: str | None = None,
    limit: int | None = None,
) -> FailedJobRecoveryStats:
    """Select and optionally requeue exhausted failed jobs."""

    if not job_type.strip():
        raise ValueError("job_type must not be empty")
    if limit is not None and limit < 1:
        raise ValueError("limit must be greater than zero")

    async with session_factory() as session:
        query = (
            select(Job.id)
            .where(
                Job.job_type == job_type,
                Job.status == "failed",
                Job.attempt_count >= Job.max_attempts,
            )
            .order_by(Job.updated_at.asc(), Job.id.asc())
        )
        if error_contains is not None:
            query = query.where(Job.last_error.contains(error_contains))
        if limit is not None:
            query = query.limit(limit)
        if apply:
            query = query.with_for_update(skip_locked=True)
        job_ids = tuple((await session.scalars(query)).all())
        stats = FailedJobRecoveryStats(
            job_type=job_type,
            selected_job_ids=job_ids,
            applied=apply,
        )
        if not apply or not job_ids:
            return stats

        await session.execute(
            update(Job)
            .where(
                Job.id.in_(job_ids),
                Job.status == "failed",
                Job.attempt_count >= Job.max_attempts,
            )
            .values(
                status="queued",
                attempt_count=0,
                run_after=None,
                locked_at=None,
                locked_by=None,
                last_error=None,
                updated_at=datetime.now(UTC),
            )
        )
        await session.commit()
        return stats


async def _run(
    *,
    job_type: str,
    apply: bool,
    error_contains: str | None,
    limit: int | None,
) -> FailedJobRecoveryStats:
    settings = MlConfig()
    engine = create_async_engine_from_config(
        DatabaseConfig(database_url=settings.postgres_database_url)
    )
    try:
        return await recover_failed_jobs(
            create_async_sessionmaker(engine),
            job_type=job_type,
            apply=apply,
            error_contains=error_contains,
            limit=limit,
        )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-type", required=True)
    parser.add_argument("--error-contains")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    stats = asyncio.run(
        _run(
            job_type=args.job_type,
            apply=args.apply,
            error_contains=args.error_contains,
            limit=args.limit,
        )
    )
    action = "requeued" if stats.applied else "would requeue"
    print(f"{action} {stats.selected_jobs} exhausted {stats.job_type} jobs")
    for job_id in stats.selected_job_ids:
        print(job_id)


if __name__ == "__main__":
    main()
