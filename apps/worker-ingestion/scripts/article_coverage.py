"""Read-only article coverage reporting by source and period."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum

from shkandal_database.models import Article, Source
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from worker_ingestion.discovery.sources import CURATED_SOURCES, SourceConfig


class CoverageGroupBy(StrEnum):
    """Supported date period granularities for article coverage."""

    DAY = "day"
    MONTH = "month"


@dataclass(frozen=True)
class ArticleCoverageRow:
    """Aggregated article counts for one source and one date period."""

    source_slug: str
    source_name: str
    source_type: str
    period_start: date | None
    article_count: int


@dataclass(frozen=True)
class SourceCoverage:
    """Coverage summary for one source."""

    slug: str
    name: str
    source_type: str
    total_articles: int
    undated_articles: int
    period_counts: dict[date, int]
    missing_periods: tuple[date, ...]
    is_curated: bool


@dataclass(frozen=True)
class ArticleCoverageReport:
    """Complete article coverage report."""

    group_by: CoverageGroupBy
    since: date | None
    until: date | None
    sources: tuple[SourceCoverage, ...]

    @property
    def total_articles(self) -> int:
        """Return the total number of articles represented by the report."""

        return sum(source.total_articles for source in self.sources)

    @property
    def sources_without_articles(self) -> tuple[SourceCoverage, ...]:
        """Return sources with no stored articles."""

        return tuple(source for source in self.sources if source.total_articles == 0)

    @property
    def sources_with_articles(self) -> tuple[SourceCoverage, ...]:
        """Return sources with at least one stored article."""

        return tuple(source for source in self.sources if source.total_articles > 0)


async def load_article_coverage_report(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    group_by: CoverageGroupBy = CoverageGroupBy.MONTH,
    since: date | None = None,
    until: date | None = None,
    source_slug: str | None = None,
) -> ArticleCoverageReport:
    """Load article coverage from PostgreSQL without mutating state."""

    async with session_factory() as session:
        rows = await _load_article_coverage_rows(
            session,
            group_by=group_by,
            since=since,
            until=until,
            source_slug=source_slug,
        )

    curated_sources = _selected_curated_sources(source_slug)
    return build_article_coverage_report(
        rows,
        curated_sources=curated_sources,
        group_by=group_by,
        since=since,
        until=until,
    )


def build_article_coverage_report(
    rows: list[ArticleCoverageRow],
    *,
    curated_sources: tuple[SourceConfig, ...] = CURATED_SOURCES,
    group_by: CoverageGroupBy = CoverageGroupBy.MONTH,
    since: date | None = None,
    until: date | None = None,
) -> ArticleCoverageReport:
    """Build a deterministic coverage report from aggregated article rows."""

    source_details: dict[str, tuple[str, str, bool]] = {
        source.slug: (source.name, source.source_type, True) for source in curated_sources
    }
    counts: dict[str, dict[date, int]] = {source.slug: {} for source in curated_sources}
    undated_counts: dict[str, int] = {source.slug: 0 for source in curated_sources}

    for row in rows:
        source_details.setdefault(row.source_slug, (row.source_name, row.source_type, False))
        counts.setdefault(row.source_slug, {})
        undated_counts.setdefault(row.source_slug, 0)

        if row.period_start is None:
            undated_counts[row.source_slug] += row.article_count
        else:
            period = _period_start(row.period_start, group_by)
            counts[row.source_slug][period] = (
                counts[row.source_slug].get(period, 0) + row.article_count
            )

    source_coverages = []
    for slug in sorted(source_details):
        name, source_type, is_curated = source_details[slug]
        period_counts = dict(sorted(counts.get(slug, {}).items()))
        undated_articles = undated_counts.get(slug, 0)
        total_articles = undated_articles + sum(period_counts.values())
        missing_periods = _missing_periods(
            period_counts,
            group_by=group_by,
            since=since,
            until=until,
        )
        source_coverages.append(
            SourceCoverage(
                slug=slug,
                name=name,
                source_type=source_type,
                total_articles=total_articles,
                undated_articles=undated_articles,
                period_counts=period_counts,
                missing_periods=missing_periods,
                is_curated=is_curated,
            )
        )

    return ArticleCoverageReport(
        group_by=group_by,
        since=since,
        until=until,
        sources=tuple(source_coverages),
    )


def render_article_coverage_markdown(report: ArticleCoverageReport) -> str:
    """Render a coverage report as Markdown for humans."""

    lines = [
        "# Article Coverage Report",
        "",
        f"- Grouping: `{report.group_by.value}`",
        f"- Expected window: {_format_window(report.since, report.until)}",
        f"- Total sources: {len(report.sources)}",
        f"- Sources with articles: {len(report.sources_with_articles)}",
        f"- Sources without articles: {len(report.sources_without_articles)}",
        f"- Total articles: {report.total_articles}",
        "",
    ]

    lines.extend(_render_sources_without_articles(report.sources_without_articles))
    lines.extend(_render_sources_with_articles(report.sources_with_articles))
    return "\n".join(lines).rstrip() + "\n"


async def _load_article_coverage_rows(
    session: AsyncSession,
    *,
    group_by: CoverageGroupBy,
    since: date | None,
    until: date | None,
    source_slug: str | None,
) -> list[ArticleCoverageRow]:
    period_expression = func.date_trunc(group_by.value, Article.published_at).cast(
        Article.published_at.type
    )
    statement: Select[tuple[str, str, str, datetime | None, int]] = (
        select(
            Source.slug,
            Source.name,
            Source.source_type,
            period_expression.label("period_start"),
            func.count(Article.id),
        )
        .join(Article, Article.source_id == Source.id)
        .group_by(Source.slug, Source.name, Source.source_type, period_expression)
        .order_by(Source.slug, period_expression)
    )
    if source_slug is not None:
        statement = statement.where(Source.slug == source_slug)
    if since is not None:
        statement = statement.where(
            Article.published_at.is_(None) | (Article.published_at >= _date_start(since))
        )
    if until is not None:
        exclusive_until = _date_start(_next_period_start(until, CoverageGroupBy.DAY))
        statement = statement.where(
            Article.published_at.is_(None) | (Article.published_at < exclusive_until)
        )

    result = await session.execute(statement)
    return [
        ArticleCoverageRow(
            source_slug=row[0],
            source_name=row[1],
            source_type=row[2],
            period_start=row[3].date() if row[3] is not None else None,
            article_count=row[4],
        )
        for row in result.all()
    ]


def _render_sources_without_articles(sources: tuple[SourceCoverage, ...]) -> list[str]:
    lines = ["## Sources Without Articles", ""]
    if not sources:
        return [*lines, "None.", ""]

    for source in sources:
        marker = "" if source.is_curated else " (not in curated source list)"
        lines.append(f"- `{source.slug}` - {source.name} [{source.source_type}]{marker}")
    lines.append("")
    return lines


def _render_sources_with_articles(sources: tuple[SourceCoverage, ...]) -> list[str]:
    lines = ["## Sources With Articles", ""]
    if not sources:
        return [*lines, "None.", ""]

    for source in sources:
        marker = "" if source.is_curated else " (not in curated source list)"
        lines.append(f"### `{source.slug}` - {source.name}{marker}")
        lines.append("")
        lines.append(f"- Type: `{source.source_type}`")
        lines.append(f"- Total articles: {source.total_articles}")
        if source.undated_articles:
            lines.append(f"- Articles without `published_at`: {source.undated_articles}")
        lines.append(f"- Covered periods: {_format_period_counts(source.period_counts)}")
        lines.append(f"- Missing periods: {_format_periods(source.missing_periods)}")
        lines.append("")
    return lines


def _format_period_counts(period_counts: dict[date, int]) -> str:
    if not period_counts:
        return "none"
    return ", ".join(f"{period.isoformat()} ({count})" for period, count in period_counts.items())


def _format_periods(periods: tuple[date, ...]) -> str:
    if not periods:
        return "none"
    return ", ".join(period.isoformat() for period in periods)


def _format_window(since: date | None, until: date | None) -> str:
    if since is None and until is None:
        return "source first dated article through source last dated article"
    since_text = since.isoformat() if since else "unbounded"
    until_text = until.isoformat() if until else "unbounded"
    return f"{since_text} through {until_text}"


def _selected_curated_sources(source_slug: str | None) -> tuple[SourceConfig, ...]:
    if source_slug is None:
        return CURATED_SOURCES
    return tuple(source for source in CURATED_SOURCES if source.slug == source_slug)


def _missing_periods(
    period_counts: dict[date, int],
    *,
    group_by: CoverageGroupBy,
    since: date | None,
    until: date | None,
) -> tuple[date, ...]:
    if not period_counts and (since is None or until is None):
        return ()

    first_period = _period_start(since, group_by) if since else min(period_counts)
    last_period = _period_start(until, group_by) if until else max(period_counts)
    periods = []
    current = first_period
    while current <= last_period:
        if current not in period_counts:
            periods.append(current)
        current = _next_period_start(current, group_by)
    return tuple(periods)


def _period_start(value: date, group_by: CoverageGroupBy) -> date:
    if group_by == CoverageGroupBy.MONTH:
        return date(value.year, value.month, 1)
    return value


def _next_period_start(value: date, group_by: CoverageGroupBy) -> date:
    if group_by == CoverageGroupBy.DAY:
        return date.fromordinal(value.toordinal() + 1)
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def _date_start(value: date) -> datetime:
    return datetime(value.year, value.month, value.day, tzinfo=UTC)
