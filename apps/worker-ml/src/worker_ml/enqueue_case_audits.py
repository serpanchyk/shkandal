"""Dry-run-first Case coherence audit enqueueing and targeted reruns."""

from __future__ import annotations

import argparse
import asyncio

from shkandal_database.config import DatabaseConfig
from shkandal_database.jobs import ArticleJobStore
from shkandal_database.models import Case
from shkandal_database.session import create_async_engine_from_config, create_async_sessionmaker
from sqlalchemy import func, or_, select

from worker_ml.config import MlConfig
from worker_ml.runtime.planning import MlJobPlanner


async def run(*, apply: bool, limit: int | None, rerun_coherent_successes: bool) -> None:
    """Report or enqueue due active Cases or targeted coherent reruns."""

    settings = MlConfig()
    engine = create_async_engine_from_config(
        DatabaseConfig(database_url=settings.postgres_database_url)
    )
    try:
        session_factory = create_async_sessionmaker(engine)
        planner = MlJobPlanner(session_factory, ArticleJobStore(session_factory))
        if rerun_coherent_successes:
            async with session_factory() as session:
                selected = await session.scalar(
                    select(func.count()).select_from(
                        planner._coherent_successful_case_audit_rerun_query(limit=limit).subquery()
                    )
                )
            print(f"coherent successful audit reruns selected: {selected or 0}")
        else:
            selected_limit = limit or 5
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
            print(f"due active Cases: {due or 0}; selected limit: {selected_limit}")
        if not apply:
            print("dry run; pass --apply to enqueue")
            return
        if rerun_coherent_successes:
            stats = await planner.enqueue_coherent_successful_case_audit_reruns(
                limit=limit,
                max_attempts=settings.job_max_attempts,
            )
        else:
            stats = await planner.enqueue_due_case_audit_jobs(
                limit=limit or 5,
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
    parser = argparse.ArgumentParser(description="Enqueue Case coherence audits.")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--rerun-coherent-successes",
        action="store_true",
        help="rerun active Cases whose latest audit is coherent and job succeeded",
    )
    args = parser.parse_args()
    limit = max(1, args.limit) if args.limit is not None else None
    asyncio.run(
        run(
            apply=args.apply,
            limit=limit,
            rerun_coherent_successes=args.rerun_coherent_successes,
        )
    )


if __name__ == "__main__":
    main()
