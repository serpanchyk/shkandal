from pathlib import Path

import pytest
from worker_ingestion.config import IngestionConfig


@pytest.mark.asyncio
async def test_service_status_uses_configured_service_name() -> None:
    result = await IngestionConfig(service_name="ingestion-test").service_status()

    assert result == {"service": "ingestion-test", "status": "ok"}


def test_request_defaults_are_production_bounded() -> None:
    config = IngestionConfig()

    assert config.poll_interval_seconds == 3600
    assert config.heartbeat_max_age_seconds == 10_800
    assert config.fetch_max_attempts == 5
    assert config.request_timeout_seconds > 0
    assert config.request_concurrency > 0
    assert "Shkandal ingestion worker" in config.request_user_agent
    assert config.max_sitemap_urls_per_source > 0


def test_worker_ingestion_yaml_configures_runtime_knobs(monkeypatch: pytest.MonkeyPatch) -> None:
    worker_root = Path(__file__).parents[2]
    monkeypatch.chdir(worker_root)

    config = IngestionConfig()

    assert config.request_timeout_seconds == 20.0
    assert config.request_concurrency == 5
    assert config.request_user_agent.startswith("Shkandal ingestion worker ")
    assert "https://github.com/serpanchyk/shkandal" in config.request_user_agent
    assert "contact:" in config.request_user_agent
    assert config.max_sitemap_urls_per_source == 500
    assert config.poll_interval_seconds == 3600
