"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from shkandal_common.logging import setup_logger
from shkandal_database.config import DatabaseConfig
from shkandal_database.session import create_async_engine_from_config, create_async_sessionmaker

from shkandal_backend.config import BackendConfig
from shkandal_backend.image_urls import HttpxImageUrlChecker
from shkandal_backend.observability import (
    BackendMetrics,
    EmptyPipelineMetricsRepository,
    PipelineMetricsRepository,
    PrometheusMiddleware,
    SqlAlchemyPipelineMetricsRepository,
    metrics_response,
)
from shkandal_backend.public_repository import PublicRepository, SqlAlchemyPublicRepository
from shkandal_backend.routes import router


def create_app(
    config: BackendConfig | None = None,
    repository: PublicRepository | None = None,
    pipeline_metrics_repository: PipelineMetricsRepository | None = None,
) -> FastAPI:
    settings = config or BackendConfig()
    logger = setup_logger(settings.service_name)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = None
        image_url_checker = None
        if repository is None:
            engine = create_async_engine_from_config(
                DatabaseConfig(database_url=settings.postgres_database_url)
            )
            session_factory = create_async_sessionmaker(engine)
            image_url_checker = HttpxImageUrlChecker(
                timeout_seconds=settings.image_check_timeout_seconds,
                max_candidates=settings.image_check_max_candidates,
                cache_ttl_seconds=settings.image_check_cache_ttl_seconds,
            )
            app.state.public_repository = SqlAlchemyPublicRepository(
                session_factory,
                image_url_checker,
            )
            if pipeline_metrics_repository is None:
                app.state.pipeline_metrics_repository = SqlAlchemyPipelineMetricsRepository(
                    session_factory
                )
        else:
            app.state.public_repository = repository
        logger.info("service_started", extra={"service": settings.service_name})
        yield
        if engine is not None:
            await engine.dispose()
        if image_url_checker is not None:
            await image_url_checker.close()

    app = FastAPI(title="Shkandal API", version="0.1.0", lifespan=lifespan)
    metrics = BackendMetrics()
    if repository is not None:
        app.state.public_repository = repository
    app.state.pipeline_metrics_repository = (
        pipeline_metrics_repository or EmptyPipelineMetricsRepository()
    )
    app.add_middleware(PrometheusMiddleware, metrics=metrics)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.public_frontend_origin],
        allow_methods=["GET", "POST"],
        allow_headers=[],
    )
    app.include_router(router)

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {"service": settings.service_name, "status": "ok"}

    @app.get("/metrics", include_in_schema=False)
    async def metrics_endpoint(request: Request) -> Response:
        return await metrics_response(
            request,
            metrics,
            app.state.pipeline_metrics_repository,
        )

    return app
