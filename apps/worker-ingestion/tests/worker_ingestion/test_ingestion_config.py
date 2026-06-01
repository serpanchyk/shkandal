import pytest
from worker_ingestion.config import IngestionConfig


@pytest.mark.asyncio
async def test_service_status_uses_configured_service_name() -> None:
    result = await IngestionConfig(service_name="ingestion-test").service_status()

    assert result == {"service": "ingestion-test", "status": "ok"}


def test_request_defaults_are_production_bounded() -> None:
    config = IngestionConfig()

    assert config.request_timeout_seconds > 0
    assert config.request_concurrency > 0
    assert "Shkandal ingestion worker" in config.request_user_agent
    assert config.max_sitemap_urls_per_source > 0
