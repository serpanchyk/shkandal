"""Inspect or reset dropped-link case-resolution jobs for fallback reprocessing."""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import UUID

from shkandal_database.config import DatabaseConfig
from shkandal_database.models import ArticleCard, CaseArticle, Job, LlmRun
from shkandal_database.session import create_async_engine_from_config, create_async_sessionmaker
from sqlalchemy import Text, cast, exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from worker_ml.runtime.planning import RESOLVE_ARTICLE_CASES_JOB


@dataclass(frozen=True)
class SelectedCaseResolutionJob:
    """One case-resolution job selected for reset."""

    job_id: UUID
    article_id: UUID


@dataclass(frozen=True)
class CaseResolutionResetStats:
    """Result of one dropped-link reset selection."""

    selected_jobs: tuple[SelectedCaseResolutionJob, ...]
    applied: bool

    @property
    def selected_count(self) -> int:
        """Return the selected job count."""

        return len(self.selected_jobs)


async def reset_unconnected_case_resolution_jobs(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    apply: bool,
    limit: int | None = None,
) -> CaseResolutionResetStats:
    """Select and optionally reset case-candidate jobs orphaned after link audits."""

    if limit is not None and limit < 1:
        raise ValueError("limit must be greater than zero")

    async with session_factory() as session:
        query = (
            select(Job.id, Job.article_id)
            .join(ArticleCard, ArticleCard.article_id == Job.article_id)
            .where(
                Job.job_type == RESOLVE_ARTICLE_CASES_JOB,
                Job.status == "succeeded",
                Job.article_id.is_not(None),
                ArticleCard.is_case_candidate.is_(True),
                ~exists().where(CaseArticle.article_id == Job.article_id).correlate(Job),
                exists()
                .where(
                    LlmRun.run_type == "case_link_audit",
                    LlmRun.metadata_["article_id"].astext == cast(Job.article_id, Text),
                )
                .correlate(Job),
            )
            .order_by(Job.updated_at.asc(), Job.id.asc())
        )
        if limit is not None:
            query = query.limit(limit)
        if apply:
            query = query.with_for_update(skip_locked=True)

        selected = tuple(
            SelectedCaseResolutionJob(job_id=job_id, article_id=article_id)
            for job_id, article_id in (await session.execute(query)).all()
            if article_id is not None
        )
        stats = CaseResolutionResetStats(selected_jobs=selected, applied=apply)
        if not apply or not selected:
            return stats

        await session.execute(
            update(Job)
            .where(
                Job.id.in_([selected_job.job_id for selected_job in selected]),
                Job.job_type == RESOLVE_ARTICLE_CASES_JOB,
                Job.status == "succeeded",
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


async def _run(*, apply: bool, limit: int | None) -> CaseResolutionResetStats:
    engine = create_async_engine_from_config(DatabaseConfig())
    try:
        return await reset_unconnected_case_resolution_jobs(
            create_async_sessionmaker(engine),
            apply=apply,
            limit=limit,
        )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        stats = asyncio.run(_run(apply=args.apply, limit=args.limit))
    except (OSError, TimeoutError):
        host, port = _configured_database_target()
        print(
            (
                "could not connect to PostgreSQL"
                f"{f' at {host}:{port}' if host and port else ''}; "
                "check POSTGRES_DATABASE_URL or run the command with a matching database URL"
            ),
            file=sys.stderr,
        )
        raise SystemExit(2) from None
    action = "reset" if stats.applied else "would reset"
    print(f"{action} {stats.selected_count} dropped-link resolve_article_cases jobs")
    for selected in stats.selected_jobs:
        print(f"{selected.job_id} article_id={selected.article_id}")


def _configured_database_target() -> tuple[str | None, int | None]:
    try:
        parts = urlsplit(DatabaseConfig().async_database_url)
        return parts.hostname, parts.port
    except ValueError:
        return None, None


if __name__ == "__main__":
    main()
