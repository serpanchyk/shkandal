"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from shkandal_common.logging import setup_logger
from shkandal_database.config import DatabaseConfig
from shkandal_database.session import create_async_engine_from_config, create_async_sessionmaker

from shkandal_backend.config import BackendConfig
from shkandal_backend.public_repository import PublicRepository, SqlAlchemyPublicRepository
from shkandal_backend.routes import router


def create_app(
    config: BackendConfig | None = None,
    repository: PublicRepository | None = None,
) -> FastAPI:
    settings = config or BackendConfig()
    logger = setup_logger(settings.service_name)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = None
        if repository is None:
            engine = create_async_engine_from_config(
                DatabaseConfig(database_url=settings.postgres_database_url)
            )
            app.state.public_repository = SqlAlchemyPublicRepository(
                create_async_sessionmaker(engine)
            )
        else:
            app.state.public_repository = repository
        logger.info("service_started", extra={"service": settings.service_name})
        yield
        if engine is not None:
            await engine.dispose()

    app = FastAPI(title="Shkandal API", version="0.1.0", lifespan=lifespan)
    if repository is not None:
        app.state.public_repository = repository
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

    return app
