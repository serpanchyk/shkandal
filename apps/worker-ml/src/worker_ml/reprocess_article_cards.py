"""Inspect or regenerate all article cards after a contract or prompt change."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from shkandal_database.config import DatabaseConfig
from shkandal_database.models import ArticleCard, ArticleRelevance, Job
from shkandal_database.session import create_async_engine_from_config, create_async_sessionmaker
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from worker_ml.jobs import CREATE_ARTICLE_CARD_JOB


@dataclass(frozen=True)
class ArticleCardReprocessingStats:
    """Counts for an article-card regeneration pass."""

    cards_to_delete: int
    relevant_articles: int
    jobs_to_reset: int
    jobs_to_create: int
    applied: bool


async def reprocess_article_cards(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    apply: bool,
    max_attempts: int = 3,
) -> ArticleCardReprocessingStats:
    """Delete cards and queue fresh card jobs for all classifier-positive articles."""

    async with session_factory() as session:
        if apply:
            jobs = list(
                (
                    await session.scalars(
                        select(Job).where(Job.job_type == CREATE_ARTICLE_CARD_JOB).with_for_update()
                    )
                ).all()
            )
            if any(job.status == "running" for job in jobs):
                raise RuntimeError("cannot reprocess article cards while card jobs are running")
        else:
            jobs = list(
                (
                    await session.scalars(
                        select(Job).where(Job.job_type == CREATE_ARTICLE_CARD_JOB)
                    )
                ).all()
            )

        relevant_article_ids = tuple(
            (
                await session.scalars(
                    select(ArticleRelevance.article_id).where(
                        ArticleRelevance.is_relevant.is_(True)
                    )
                )
            ).all()
        )
        cards_to_delete = int(
            await session.scalar(select(func.count()).select_from(ArticleCard)) or 0
        )
        relevant_id_set = set(relevant_article_ids)
        existing_jobs = {job.article_id: job for job in jobs if job.article_id in relevant_id_set}
        missing_job_ids = relevant_id_set - existing_jobs.keys()
        stats = ArticleCardReprocessingStats(
            cards_to_delete=cards_to_delete,
            relevant_articles=len(relevant_article_ids),
            jobs_to_reset=len(existing_jobs),
            jobs_to_create=len(missing_job_ids),
            applied=apply,
        )
        if not apply:
            return stats

        await session.execute(delete(ArticleCard))
        reset_at = datetime.now(UTC)
        if relevant_article_ids:
            statement = insert(Job).values(
                [
                    {
                        "id": uuid4(),
                        "job_type": CREATE_ARTICLE_CARD_JOB,
                        "article_id": article_id,
                        "status": "queued",
                        "payload": {"article_id": str(article_id)},
                        "attempt_count": 0,
                        "max_attempts": max_attempts,
                    }
                    for article_id in relevant_article_ids
                ]
            )
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[Job.job_type, Job.article_id],
                    set_={
                        "status": "queued",
                        "payload": statement.excluded.payload,
                        "attempt_count": 0,
                        "max_attempts": max_attempts,
                        "run_after": None,
                        "locked_at": None,
                        "locked_by": None,
                        "last_error": None,
                        "updated_at": reset_at,
                    },
                )
            )
        await session.commit()
        return stats


async def _run(*, apply: bool, max_attempts: int) -> ArticleCardReprocessingStats:
    engine = create_async_engine_from_config(DatabaseConfig())
    try:
        return await reprocess_article_cards(
            create_async_sessionmaker(engine),
            apply=apply,
            max_attempts=max_attempts,
        )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--max-attempts", type=int, default=3)
    args = parser.parse_args()
    stats = asyncio.run(_run(apply=args.apply, max_attempts=args.max_attempts))
    action = "regenerated queue for" if stats.applied else "would regenerate queue for"
    print(
        f"{action} {stats.relevant_articles} relevant articles: "
        f"delete {stats.cards_to_delete} cards, reset {stats.jobs_to_reset} jobs, "
        f"create {stats.jobs_to_create} jobs"
    )


if __name__ == "__main__":
    main()
