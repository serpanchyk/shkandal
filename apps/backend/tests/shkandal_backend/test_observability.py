"""Tests for backend Prometheus metrics."""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock

import httpx
from fastapi import HTTPException
from shkandal_backend.app import create_app
from shkandal_backend.config import BackendConfig
from shkandal_backend.observability import SqlAlchemyPipelineMetricsRepository


class StubPipelineMetricsRepository:
    async def render(self, *, now: datetime | None = None) -> str:
        return 'shkandal_jobs{job_type="classify_article",status="queued"} 2\n'


def _mock_session_factory(results: list[list[tuple[Any, ...]]]) -> Mock:
    session = MagicMock()
    execute_results = []
    for rows in results:
        result = MagicMock()
        result.all.return_value = rows
        execute_results.append(result)
    session.execute = AsyncMock(side_effect=execute_results)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=None)
    return Mock(return_value=context)


async def test_metrics_exposes_runtime_http_and_pipeline_metrics() -> None:
    app = create_app(
        BackendConfig(service_name="backend-test"),
        pipeline_metrics_repository=StubPipelineMetricsRepository(),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        assert (await client.get("/healthz")).status_code == 200
        metrics = (await client.get("/metrics")).text

    assert "process_cpu_seconds_total" in metrics
    assert (
        'shkandal_backend_http_requests_total{method="GET",route="/healthz",status_code="200"}'
        in metrics
    )
    assert 'shkandal_jobs{job_type="classify_article",status="queued"} 2' in metrics


async def test_metrics_uses_route_templates_instead_of_raw_paths() -> None:
    repository = MagicMock()
    repository.case_page = AsyncMock(
        side_effect=HTTPException(status_code=500, detail="repository failure")
    )
    app = create_app(BackendConfig(service_name="backend-test"), repository=repository)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        assert (await client.get("/api/cases/raw-case-id")).status_code == 500
        metrics = (await client.get("/metrics")).text

    assert 'route="/api/cases/{slug}"' in metrics
    assert "raw-case-id" not in metrics
    assert 'shkandal_backend_http_errors_total{method="GET",route="/api/cases/{slug}"}' in metrics


async def test_pipeline_metrics_repository_renders_aggregates() -> None:
    now = datetime(2026, 6, 12, 12, 0, tzinfo=UTC)
    session_factory = _mock_session_factory(
        [
            [("classify_article", "queued", 3), ("create_article_card", "failed", 1)],
            [("classify_article", now - timedelta(minutes=10))],
            [("article_card", "failed", 2)],
            [("shared-provider", "provider_long", now + timedelta(minutes=30))],
        ]
    )

    metrics = await SqlAlchemyPipelineMetricsRepository(session_factory).render(now=now)

    assert 'shkandal_jobs{job_type="classify_article",status="queued"} 3' in metrics
    assert 'shkandal_job_oldest_queued_age_seconds{job_type="classify_article"} 600.0' in metrics
    assert 'shkandal_llm_runs_recent{run_type="article_card",status="failed"} 2' in metrics
    assert 'shkandal_llm_cooldown_active{scope="shared-provider",kind="provider_long"} 1' in metrics
