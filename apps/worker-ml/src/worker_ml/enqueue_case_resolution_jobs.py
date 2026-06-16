"""Inspect or enqueue Case-resolution jobs for existing Article Cards."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass

from shkandal_database.config import DatabaseConfig
from shkandal_database.jobs import ArticleJobStore
from shkandal_database.models import ArticleCard, Job
from shkandal_database.session import create_async_engine_from_config, create_async_sessionmaker
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from worker_ml.runtime.planning import RESOLVE_ARTICLE_CASES_JOB


@dataclass(frozen=True)
class CaseResolutionEnqueueStats:
    """Counts for a Case-resolution job enqueue pass."""

    selected_cards: int
    inserted_jobs: int
    requeued_jobs: int
    existing_jobs: int
    applied: bool

    @property
    def ensured_jobs(self) -> int:
        """Return jobs inserted or requeued by the apply pass."""

        return self.inserted_jobs + self.requeued_jobs


async def enqueue_case_resolution_jobs(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    apply: bool,
    max_attempts: int = 3,
    limit: int | None = None,
) -> CaseResolutionEnqueueStats:
    """Queue one Case-resolution job for each case-candidate Article Card."""

    if limit is not None and limit < 1:
        raise ValueError("limit must be greater than zero")

    async with session_factory() as session:
        query = (
            select(ArticleCard.article_id)
            .where(ArticleCard.is_case_candidate.is_(True))
            .order_by(ArticleCard.created_at.asc(), ArticleCard.article_id.asc())
        )
        if limit is not None:
            query = query.limit(limit)
        article_ids = tuple((await session.scalars(query)).all())

        if not apply:
            existing_jobs = int(
                await session.scalar(
                    select(func.count())
                    .select_from(Job)
                    .where(
                        Job.job_type == RESOLVE_ARTICLE_CASES_JOB,
                        Job.article_id.in_(article_ids),
                    )
                )
                or 0
            )
            return CaseResolutionEnqueueStats(
                selected_cards=len(article_ids),
                inserted_jobs=0,
                requeued_jobs=0,
                existing_jobs=existing_jobs,
                applied=False,
            )

    job_store = ArticleJobStore(session_factory)
    result = await job_store.enqueue_article_jobs(
        job_type=RESOLVE_ARTICLE_CASES_JOB,
        article_ids=list(article_ids),
        max_attempts=max_attempts,
    )
    return CaseResolutionEnqueueStats(
        selected_cards=len(article_ids),
        inserted_jobs=result.inserted_jobs,
        requeued_jobs=result.requeued_jobs,
        existing_jobs=result.existing_jobs,
        applied=True,
    )


async def _run(
    *,
    apply: bool,
    max_attempts: int,
    limit: int | None,
) -> CaseResolutionEnqueueStats:
    engine = create_async_engine_from_config(DatabaseConfig())
    try:
        return await enqueue_case_resolution_jobs(
            create_async_sessionmaker(engine),
            apply=apply,
            max_attempts=max_attempts,
            limit=limit,
        )
    finally:
        await engine.dispose()


def main() -> None:
    """Run the Case-resolution enqueue CLI."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    stats = asyncio.run(
        _run(
            apply=args.apply,
            max_attempts=args.max_attempts,
            limit=args.limit,
        )
    )
    action = "queued" if stats.applied else "would queue"
    print(
        f"{action} {stats.ensured_jobs} {RESOLVE_ARTICLE_CASES_JOB} jobs "
        f"for {stats.selected_cards} case-candidate article cards "
        f"({stats.inserted_jobs} inserted, {stats.requeued_jobs} requeued, "
        f"{stats.existing_jobs} existing)"
    )


if __name__ == "__main__":
    main()
