"""Prometheus metrics for the backend and durable pipeline state."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Protocol

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    GCCollector,
    Histogram,
    PlatformCollector,
    ProcessCollector,
    generate_latest,
)
from shkandal_database.models import Job, LlmCooldown, LlmRun
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

METRICS_PATH = "/metrics"
RECENT_LLM_WINDOW = timedelta(hours=24)


class PipelineMetricsRepository(Protocol):
    """Read-only source for durable pipeline metrics."""

    async def render(self, *, now: datetime | None = None) -> str:
        """Render application-specific metrics in Prometheus text format."""


class EmptyPipelineMetricsRepository:
    """Pipeline metrics source used when an app has no database repository."""

    async def render(self, *, now: datetime | None = None) -> str:
        return ""


class SqlAlchemyPipelineMetricsRepository:
    """Read pipeline aggregate state from PostgreSQL."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def render(self, *, now: datetime | None = None) -> str:
        checked_at = now or datetime.now(UTC)
        async with self._session_factory() as session:
            jobs = (
                await session.execute(
                    select(Job.job_type, Job.status, func.count()).group_by(
                        Job.job_type, Job.status
                    )
                )
            ).all()
            oldest_queued = (
                await session.execute(
                    select(Job.job_type, func.min(Job.created_at))
                    .where(Job.status == "queued")
                    .group_by(Job.job_type)
                )
            ).all()
            llm_runs = (
                await session.execute(
                    select(LlmRun.run_type, LlmRun.status, func.count())
                    .where(LlmRun.created_at >= checked_at - RECENT_LLM_WINDOW)
                    .group_by(LlmRun.run_type, LlmRun.status)
                )
            ).all()
            cooldowns = (
                await session.execute(
                    select(LlmCooldown.scope, LlmCooldown.cooldown_kind, LlmCooldown.resume_at)
                )
            ).all()

        lines = [
            "# HELP shkandal_jobs Current durable jobs by type and status.",
            "# TYPE shkandal_jobs gauge",
        ]
        lines.extend(
            f'shkandal_jobs{{job_type="{_escape(job_type)}",status="{_escape(status)}"}} {count}'
            for job_type, status, count in jobs
        )
        lines.extend(
            [
                "# HELP shkandal_job_oldest_queued_age_seconds Age of the oldest queued job.",
                "# TYPE shkandal_job_oldest_queued_age_seconds gauge",
            ]
        )
        lines.extend(
            f'shkandal_job_oldest_queued_age_seconds{{job_type="{_escape(job_type)}"}} '
            f"{max(0.0, (checked_at - created_at).total_seconds())}"
            for job_type, created_at in oldest_queued
        )
        lines.extend(
            [
                "# HELP shkandal_llm_runs_recent LLM runs created during the previous 24 hours.",
                "# TYPE shkandal_llm_runs_recent gauge",
            ]
        )
        lines.extend(
            "shkandal_llm_runs_recent"
            f'{{run_type="{_escape(run_type)}",status="{_escape(status)}"}} '
            f"{count}"
            for run_type, status, count in llm_runs
        )
        lines.extend(
            [
                "# HELP shkandal_llm_cooldown_active Whether a durable LLM cooldown is active.",
                "# TYPE shkandal_llm_cooldown_active gauge",
                "# HELP shkandal_llm_cooldown_resume_timestamp_seconds "
                "Durable LLM cooldown expiry.",
                "# TYPE shkandal_llm_cooldown_resume_timestamp_seconds gauge",
            ]
        )
        for scope, kind, resume_at in cooldowns:
            labels = f'scope="{_escape(scope)}",kind="{_escape(kind)}"'
            lines.append(f"shkandal_llm_cooldown_active{{{labels}}} {int(resume_at > checked_at)}")
            lines.append(
                f"shkandal_llm_cooldown_resume_timestamp_seconds{{{labels}}} "
                f"{resume_at.timestamp()}"
            )
        return "\n".join(lines) + "\n"


class BackendMetrics:
    """Own the backend-local Prometheus registry and HTTP middleware metrics."""

    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        GCCollector(registry=self.registry)
        PlatformCollector(registry=self.registry)
        ProcessCollector(registry=self.registry)
        self.requests = Counter(
            "shkandal_backend_http_requests_total",
            "Backend HTTP requests.",
            ("method", "route", "status_code"),
            registry=self.registry,
        )
        self.errors = Counter(
            "shkandal_backend_http_errors_total",
            "Backend HTTP requests returning a 5xx response.",
            ("method", "route"),
            registry=self.registry,
        )
        self.duration = Histogram(
            "shkandal_backend_http_request_duration_seconds",
            "Backend HTTP request latency.",
            ("method", "route"),
            registry=self.registry,
        )

    def render(self) -> bytes:
        return generate_latest(self.registry)


class PrometheusMiddleware:
    """Record HTTP metrics after FastAPI has resolved the route template."""

    def __init__(self, app: ASGIApp, metrics: BackendMetrics) -> None:
        self.app = app
        self.metrics = metrics

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") == METRICS_PATH:
            await self.app(scope, receive, send)
            return

        started_at = time.monotonic()
        status_code = 500

        async def capture_status(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, capture_status)
        finally:
            route = getattr(scope.get("route"), "path", "unmatched")
            method = scope.get("method", "UNKNOWN")
            self.metrics.requests.labels(method, route, str(status_code)).inc()
            self.metrics.duration.labels(method, route).observe(time.monotonic() - started_at)
            if status_code >= 500:
                self.metrics.errors.labels(method, route).inc()


async def metrics_response(
    request: Request,
    metrics: BackendMetrics,
    pipeline_metrics: PipelineMetricsRepository,
) -> Response:
    """Return backend and PostgreSQL-backed metrics."""

    runtime_metrics = metrics.render().decode()
    pipeline = await pipeline_metrics.render()
    return Response(runtime_metrics + pipeline, media_type=CONTENT_TYPE_LATEST)


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')
