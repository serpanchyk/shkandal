"""Dry-run-first initial Case coherence audit enqueueing."""

from __future__ import annotations

import argparse
import asyncio

from shkandal_database.config import DatabaseConfig
from shkandal_database.jobs import ArticleJobStore
from shkandal_database.models import Case
from shkandal_database.session import create_async_engine_from_config, create_async_sessionmaker
from sqlalchemy import func, or_, select

from worker_ml.config import MlConfig
from worker_ml.jobs import MlJobPlanner


async def run(*, apply: bool, limit: int) -> None:
    """Report or enqueue the oldest due active Cases."""

    settings = MlConfig()
    engine = create_async_engine_from_config(
        DatabaseConfig(database_url=settings.postgres_database_url)
    )
    try:
        session_factory = create_async_sessionmaker(engine)
        async with session_factory() as session:
            due = await session.scalar(
                select(func.count())
                .select_from(Case)
                .where(
                    Case.status == "active",
                    or_(
                        Case.last_audited_revision < Case.evidence_revision,
                        Case.last_audited_at.is_(None),
                    ),
                )
            )
        print(f"due active Cases: {due or 0}; selected limit: {limit}")
        if not apply:
            print("dry run; pass --apply to enqueue the canary batch")
            return
        planner = MlJobPlanner(session_factory, ArticleJobStore(session_factory))
        stats = await planner.enqueue_due_case_audit_jobs(
            limit=limit,
            max_attempts=settings.job_max_attempts,
            interval_days=settings.case_audit_interval_days,
        )
        print(
            f"enqueued: {stats.inserted_jobs}; requeued: {stats.requeued_jobs}; "
            f"existing: {stats.existing_jobs}"
        )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Enqueue initial Case coherence audit canary.")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    asyncio.run(run(apply=args.apply, limit=max(1, args.limit)))


if __name__ == "__main__":
    main()
