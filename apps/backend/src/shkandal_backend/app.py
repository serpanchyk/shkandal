"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from shkandal_common.logging import setup_logger

from shkandal_backend.config import BackendConfig


def create_app(config: BackendConfig | None = None) -> FastAPI:
    settings = config or BackendConfig()
    logger = setup_logger(settings.service_name)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info("service_started", extra={"service": settings.service_name})
        yield

    app = FastAPI(title="Shkandal API", version="0.1.0", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {"service": settings.service_name, "status": "ok"}

    return app
