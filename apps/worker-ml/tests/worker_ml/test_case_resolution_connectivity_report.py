from datetime import UTC, datetime
from uuid import UUID

import pytest
from worker_ml.cases.connectivity_report import (
    CaseResolutionConnectivityReport,
    UnconnectedResolvedArticle,
    load_case_resolution_connectivity_report,
    render_case_resolution_connectivity_report,
)


def test_report_calculates_connection_rates() -> None:
    report = CaseResolutionConnectivityReport(
        case_candidate_articles=12,
        resolution_jobs_succeeded=10,
        resolution_jobs_failed=1,
        resolution_jobs_unfinished=1,
        linked_after_succeeded_resolution=7,
        unconnected_after_succeeded_resolution=3,
        examples=(),
    )

    assert report.resolved_connection_rate == 0.7
    assert report.resolved_unconnected_rate == 0.3


def test_report_handles_empty_resolution_counts() -> None:
    report = CaseResolutionConnectivityReport(
        case_candidate_articles=0,
        resolution_jobs_succeeded=0,
        resolution_jobs_failed=0,
        resolution_jobs_unfinished=0,
        linked_after_succeeded_resolution=0,
        unconnected_after_succeeded_resolution=0,
        examples=(),
    )

    assert report.resolved_connection_rate == 0
    assert report.resolved_unconnected_rate == 0


def test_report_renders_recent_unconnected_examples() -> None:
    article_id = UUID("00000000-0000-0000-0000-000000000001")
    report = CaseResolutionConnectivityReport(
        case_candidate_articles=1,
        resolution_jobs_succeeded=1,
        resolution_jobs_failed=0,
        resolution_jobs_unfinished=0,
        linked_after_succeeded_resolution=0,
        unconnected_after_succeeded_resolution=1,
        examples=(
            UnconnectedResolvedArticle(
                article_id=article_id,
                source_slug="pravda",
                source_title="Source title",
                card_title_uk="Картка",
                published_at=datetime(2026, 6, 15, tzinfo=UTC),
                resolved_at=datetime(2026, 6, 16, tzinfo=UTC),
            ),
        ),
    )

    markdown = render_case_resolution_connectivity_report(report)

    assert "Unconnected after succeeded resolution: 1" in markdown
    assert "Connection rate after succeeded resolution: 0.0%" in markdown
    assert f"`{article_id}` [pravda] 2026-06-15 - Source title" in markdown


@pytest.mark.asyncio
async def test_report_rejects_negative_example_limit() -> None:
    with pytest.raises(ValueError, match="example_limit"):
        await load_case_resolution_connectivity_report(
            pytest.fail,  # type: ignore[arg-type]
            example_limit=-1,
        )
