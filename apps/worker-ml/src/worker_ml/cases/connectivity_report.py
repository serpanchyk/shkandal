"""Read-only reporting for article-to-Case resolution connectivity."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from shkandal_database.jobs import JOB_STATUS_FAILED, JOB_STATUS_SUCCEEDED
from shkandal_database.models import Article, ArticleCard, CaseArticle, Job, Source
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from worker_ml.runtime.planning import RESOLVE_ARTICLE_CASES_JOB


@dataclass(frozen=True)
class UnconnectedResolvedArticle:
    """One case-candidate article whose Case-resolution job finished without a Case link."""

    article_id: UUID
    source_slug: str
    source_title: str | None
    card_title_uk: str
    published_at: datetime | None
    resolved_at: datetime


@dataclass(frozen=True)
class CaseResolutionConnectivityReport:
    """Aggregate counts for the Case-resolution connection funnel."""

    case_candidate_articles: int
    resolution_jobs_succeeded: int
    resolution_jobs_failed: int
    resolution_jobs_unfinished: int
    linked_after_succeeded_resolution: int
    unconnected_after_succeeded_resolution: int
    examples: tuple[UnconnectedResolvedArticle, ...]

    @property
    def resolved_connection_rate(self) -> float:
        """Return the share of succeeded resolution jobs that produced a Case link."""

        if self.resolution_jobs_succeeded == 0:
            return 0.0
        return self.linked_after_succeeded_resolution / self.resolution_jobs_succeeded

    @property
    def resolved_unconnected_rate(self) -> float:
        """Return the share of succeeded resolution jobs that produced no Case link."""

        if self.resolution_jobs_succeeded == 0:
            return 0.0
        return self.unconnected_after_succeeded_resolution / self.resolution_jobs_succeeded


async def load_case_resolution_connectivity_report(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    example_limit: int = 20,
) -> CaseResolutionConnectivityReport:
    """Load read-only Case-resolution connectivity counts from PostgreSQL."""

    if example_limit < 0:
        raise ValueError("example_limit must be non-negative")

    async with session_factory() as session:
        case_candidate_articles = int(
            await session.scalar(
                select(func.count()).select_from(ArticleCard).where(_case_candidate_filter())
            )
            or 0
        )
        resolution_jobs_succeeded = int(
            await session.scalar(
                select(func.count()).select_from(Job).where(_resolution_job_filter())
            )
            or 0
        )
        resolution_jobs_failed = int(
            await session.scalar(
                select(func.count())
                .select_from(Job)
                .where(_resolution_job_filter(JOB_STATUS_FAILED))
            )
            or 0
        )
        resolution_jobs_unfinished = int(
            await session.scalar(
                select(func.count())
                .select_from(Job)
                .where(
                    Job.job_type == RESOLVE_ARTICLE_CASES_JOB,
                    Job.article_id.is_not(None),
                    Job.status.not_in((JOB_STATUS_SUCCEEDED, JOB_STATUS_FAILED)),
                )
            )
            or 0
        )
        linked_after_succeeded_resolution = int(
            await session.scalar(_linked_after_succeeded_resolution_query()) or 0
        )
        unconnected_after_succeeded_resolution = int(
            await session.scalar(_unconnected_after_succeeded_resolution_query()) or 0
        )
        examples = tuple(
            UnconnectedResolvedArticle(
                article_id=row.article_id,
                source_slug=row.source_slug,
                source_title=row.source_title,
                card_title_uk=row.card_title_uk,
                published_at=row.published_at,
                resolved_at=row.resolved_at,
            )
            for row in (
                await session.execute(
                    _unconnected_examples_query(limit=example_limit),
                )
            ).all()
        )

    return CaseResolutionConnectivityReport(
        case_candidate_articles=case_candidate_articles,
        resolution_jobs_succeeded=resolution_jobs_succeeded,
        resolution_jobs_failed=resolution_jobs_failed,
        resolution_jobs_unfinished=resolution_jobs_unfinished,
        linked_after_succeeded_resolution=linked_after_succeeded_resolution,
        unconnected_after_succeeded_resolution=unconnected_after_succeeded_resolution,
        examples=examples,
    )


def render_case_resolution_connectivity_report(
    report: CaseResolutionConnectivityReport,
) -> str:
    """Render Case-resolution connectivity counts as Markdown."""

    lines = [
        "# Case Resolution Connectivity Report",
        "",
        f"- Case-candidate article cards: {report.case_candidate_articles}",
        f"- Succeeded `{RESOLVE_ARTICLE_CASES_JOB}` jobs: {report.resolution_jobs_succeeded}",
        f"- Linked after succeeded resolution: {report.linked_after_succeeded_resolution}",
        (
            "- Unconnected after succeeded resolution: "
            f"{report.unconnected_after_succeeded_resolution}"
        ),
        (
            "- Connection rate after succeeded resolution: "
            f"{_format_rate(report.resolved_connection_rate)}"
        ),
        (
            "- Unconnected rate after succeeded resolution: "
            f"{_format_rate(report.resolved_unconnected_rate)}"
        ),
        f"- Failed `{RESOLVE_ARTICLE_CASES_JOB}` jobs: {report.resolution_jobs_failed}",
        f"- Unfinished `{RESOLVE_ARTICLE_CASES_JOB}` jobs: {report.resolution_jobs_unfinished}",
        "",
        "## Recent Unconnected Examples",
        "",
    ]
    if not report.examples:
        lines.extend(["None.", ""])
        return "\n".join(lines).rstrip() + "\n"

    for example in report.examples:
        title = example.source_title or example.card_title_uk
        lines.append(
            "- "
            f"`{example.article_id}` "
            f"[{example.source_slug}] "
            f"{_format_datetime(example.published_at)} "
            f"- {title}"
        )
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _case_candidate_filter() -> ColumnElement[bool]:
    return ArticleCard.is_case_candidate.is_(True)


def _resolution_job_filter(status: str = JOB_STATUS_SUCCEEDED) -> ColumnElement[bool]:
    return (
        (Job.job_type == RESOLVE_ARTICLE_CASES_JOB)
        & (Job.article_id.is_not(None))
        & (Job.status == status)
    )


def _linked_after_succeeded_resolution_query() -> Select[tuple[int]]:
    linked_article_ids = (
        select(CaseArticle.article_id)
        .join(ArticleCard, ArticleCard.article_id == CaseArticle.article_id)
        .join(
            Job,
            (Job.article_id == CaseArticle.article_id)
            & (Job.job_type == RESOLVE_ARTICLE_CASES_JOB)
            & (Job.status == JOB_STATUS_SUCCEEDED),
        )
        .where(_case_candidate_filter())
        .distinct()
        .subquery()
    )
    return select(func.count()).select_from(linked_article_ids)


def _unconnected_after_succeeded_resolution_query() -> Select[tuple[int]]:
    return (
        select(func.count())
        .select_from(ArticleCard)
        .join(
            Job,
            (Job.article_id == ArticleCard.article_id)
            & (Job.job_type == RESOLVE_ARTICLE_CASES_JOB)
            & (Job.status == JOB_STATUS_SUCCEEDED),
        )
        .outerjoin(CaseArticle, CaseArticle.article_id == ArticleCard.article_id)
        .where(_case_candidate_filter(), CaseArticle.id.is_(None))
    )


def _unconnected_examples_query(
    *, limit: int
) -> Select[tuple[UUID, str, str | None, str, datetime | None, datetime]]:
    return (
        select(
            Article.id.label("article_id"),
            Source.slug.label("source_slug"),
            Article.title.label("source_title"),
            ArticleCard.title_uk.label("card_title_uk"),
            Article.published_at.label("published_at"),
            Job.updated_at.label("resolved_at"),
        )
        .select_from(ArticleCard)
        .join(Article, Article.id == ArticleCard.article_id)
        .join(Source, Source.id == Article.source_id)
        .join(
            Job,
            (Job.article_id == ArticleCard.article_id)
            & (Job.job_type == RESOLVE_ARTICLE_CASES_JOB)
            & (Job.status == JOB_STATUS_SUCCEEDED),
        )
        .outerjoin(CaseArticle, CaseArticle.article_id == ArticleCard.article_id)
        .where(_case_candidate_filter(), CaseArticle.id.is_(None))
        .order_by(Job.updated_at.desc(), ArticleCard.article_id.asc())
        .limit(limit)
    )


def _format_rate(value: float) -> str:
    return f"{value:.1%}"


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return "undated"
    return value.date().isoformat()
