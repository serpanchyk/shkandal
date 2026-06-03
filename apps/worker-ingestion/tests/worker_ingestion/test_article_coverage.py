from datetime import date

from worker_ingestion.article_coverage import (
    ArticleCoverageRow,
    CoverageGroupBy,
    build_article_coverage_report,
    render_article_coverage_markdown,
)
from worker_ingestion.sources import SourceConfig


def test_report_lists_curated_sources_without_articles() -> None:
    curated_sources = (
        SourceConfig(slug="pravda", name="Українська правда", base_url="https://pravda.com.ua"),
        SourceConfig(slug="tyzhden", name="Український тиждень", base_url="https://tyzhden.ua"),
    )

    report = build_article_coverage_report(
        [
            ArticleCoverageRow(
                source_slug="pravda",
                source_name="Українська правда",
                source_type="media",
                period_start=date(2026, 3, 1),
                article_count=2,
            )
        ],
        curated_sources=curated_sources,
    )

    assert [source.slug for source in report.sources_without_articles] == ["tyzhden"]
    assert report.total_articles == 2


def test_report_detects_missing_months_between_first_and_last_article() -> None:
    report = build_article_coverage_report(
        [
            ArticleCoverageRow(
                source_slug="tyzhden",
                source_name="Український тиждень",
                source_type="media",
                period_start=date(2026, 2, 1),
                article_count=3,
            ),
            ArticleCoverageRow(
                source_slug="tyzhden",
                source_name="Український тиждень",
                source_type="media",
                period_start=date(2026, 4, 1),
                article_count=4,
            ),
        ],
        curated_sources=(
            SourceConfig(slug="tyzhden", name="Український тиждень", base_url="https://tyzhden.ua"),
        ),
        group_by=CoverageGroupBy.MONTH,
    )

    tyzhden = report.sources_with_articles[0]

    assert tyzhden.missing_periods == (date(2026, 3, 1),)


def test_report_uses_expected_window_when_provided() -> None:
    report = build_article_coverage_report(
        [
            ArticleCoverageRow(
                source_slug="pravda",
                source_name="Українська правда",
                source_type="media",
                period_start=date(2026, 6, 2),
                article_count=1,
            )
        ],
        curated_sources=(
            SourceConfig(slug="pravda", name="Українська правда", base_url="https://pravda.com.ua"),
        ),
        group_by=CoverageGroupBy.DAY,
        since=date(2026, 6, 1),
        until=date(2026, 6, 3),
    )

    pravda = report.sources_with_articles[0]

    assert pravda.missing_periods == (date(2026, 6, 1), date(2026, 6, 3))


def test_report_renders_undated_articles() -> None:
    report = build_article_coverage_report(
        [
            ArticleCoverageRow(
                source_slug="pravda",
                source_name="Українська правда",
                source_type="media",
                period_start=None,
                article_count=5,
            )
        ],
        curated_sources=(
            SourceConfig(slug="pravda", name="Українська правда", base_url="https://pravda.com.ua"),
        ),
    )

    markdown = render_article_coverage_markdown(report)

    assert "Articles without `published_at`: 5" in markdown
    assert "Covered periods: none" in markdown
