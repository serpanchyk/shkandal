"""Inspect or regenerate all article cards after a contract or prompt change."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from shkandal_database.config import DatabaseConfig
from shkandal_database.models import ArticleCard, ArticleGateDecision, Job
from shkandal_database.session import create_async_engine_from_config, create_async_sessionmaker
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from worker_ml.config import MlConfig
from worker_ml.runtime.planning import CREATE_ARTICLE_CARD_JOB


@dataclass(frozen=True)
class ArticleCardReprocessingStats:
    """Counts for an article-card regeneration pass."""

    cards_to_delete: int
    accepted_gate_articles: int
    jobs_to_reset: int
    jobs_to_create: int
    applied: bool


async def reprocess_article_cards(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    apply: bool,
    max_attempts: int | None = None,
    limit: int | None = None,
    job_upsert_batch_size: int | None = None,
) -> ArticleCardReprocessingStats:
    """Delete cards and queue fresh card jobs for all or the latest existing cards."""

    settings = MlConfig()
    resolved_max_attempts = settings.job_max_attempts if max_attempts is None else max_attempts
    resolved_job_upsert_batch_size = (
        settings.article_card_reprocess_job_upsert_batch_size
        if job_upsert_batch_size is None
        else job_upsert_batch_size
    )

    if limit is not None and limit < 1:
        raise ValueError("limit must be greater than zero")
    if resolved_job_upsert_batch_size < 1:
        raise ValueError("job_upsert_batch_size must be greater than zero")

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

        if limit is None:
            accepted_article_ids = tuple(
                (
                    await session.scalars(
                        select(ArticleGateDecision.article_id).where(
                            ArticleGateDecision.is_case_candidate.is_(True)
                        )
                    )
                ).all()
            )
            cards_to_delete = int(
                await session.scalar(select(func.count()).select_from(ArticleCard)) or 0
            )
        else:
            accepted_article_ids = tuple(
                (
                    await session.scalars(
                        select(ArticleCard.article_id)
                        .order_by(ArticleCard.created_at.desc())
                        .limit(limit)
                    )
                ).all()
            )
            cards_to_delete = len(accepted_article_ids)
        accepted_id_set = set(accepted_article_ids)
        existing_jobs = {job.article_id: job for job in jobs if job.article_id in accepted_id_set}
        missing_job_ids = accepted_id_set - existing_jobs.keys()
        stats = ArticleCardReprocessingStats(
            cards_to_delete=cards_to_delete,
            accepted_gate_articles=len(accepted_article_ids),
            jobs_to_reset=len(existing_jobs),
            jobs_to_create=len(missing_job_ids),
            applied=apply,
        )
        if not apply:
            return stats

        delete_statement = delete(ArticleCard)
        if limit is not None:
            delete_statement = delete_statement.where(
                ArticleCard.article_id.in_(accepted_article_ids)
            )
        await session.execute(delete_statement)
        reset_at = datetime.now(UTC)
        for start in range(0, len(accepted_article_ids), resolved_job_upsert_batch_size):
            await _upsert_article_card_jobs(
                session,
                article_ids=accepted_article_ids[start : start + resolved_job_upsert_batch_size],
                max_attempts=resolved_max_attempts,
                reset_at=reset_at,
            )
        await session.commit()
        return stats


async def _upsert_article_card_jobs(
    session: AsyncSession,
    *,
    article_ids: tuple[UUID, ...],
    max_attempts: int,
    reset_at: datetime,
) -> None:
    """Queue one bounded batch without exceeding asyncpg's parameter limit."""

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
            for article_id in article_ids
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


async def _run(
    *,
    apply: bool,
    max_attempts: int | None,
    limit: int | None,
) -> ArticleCardReprocessingStats:
    settings = MlConfig()
    engine = create_async_engine_from_config(
        DatabaseConfig(database_url=settings.postgres_database_url)
    )
    try:
        return await reprocess_article_cards(
            create_async_sessionmaker(engine),
            apply=apply,
            max_attempts=max_attempts,
            limit=limit,
        )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--max-attempts", type=int)
    parser.add_argument(
        "--limit",
        type=int,
        help="Regenerate only this many most recently created existing cards.",
    )
    args = parser.parse_args()
    stats = asyncio.run(
        _run(
            apply=args.apply,
            max_attempts=args.max_attempts,
            limit=args.limit,
        )
    )
    action = "regenerated queue for" if stats.applied else "would regenerate queue for"
    print(
        f"{action} {stats.accepted_gate_articles} accepted gate articles: "
        f"delete {stats.cards_to_delete} cards, reset {stats.jobs_to_reset} jobs, "
        f"create {stats.jobs_to_create} jobs"
    )


if __name__ == "__main__":
    main()
