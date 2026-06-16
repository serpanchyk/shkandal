from unittest.mock import AsyncMock, Mock

import httpx
import shkandal_backend.app as app_module
from shkandal_backend.app import create_app
from shkandal_backend.config import BackendConfig


async def test_healthz() -> None:
    app = create_app(BackendConfig(service_name="backend-test"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"service": "backend-test", "status": "ok"}


async def test_lifespan_builds_and_disposes_database_repository(monkeypatch) -> None:
    engine = Mock(dispose=AsyncMock())
    session_factory = Mock()
    monkeypatch.setattr(app_module, "create_async_engine_from_config", Mock(return_value=engine))
    monkeypatch.setattr(
        app_module,
        "create_async_sessionmaker",
        Mock(return_value=session_factory),
    )
    app = create_app(BackendConfig(service_name="backend-test"))

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            assert (await client.get("/healthz")).status_code == 200

    engine.dispose.assert_awaited_once()
