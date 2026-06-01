import pytest
from worker_ingestion.config import IngestionConfig
from worker_ingestion.main import run_once


@pytest.mark.asyncio
async def test_run_once_smoke() -> None:
    result = await run_once(IngestionConfig(service_name="ingestion-test"))

    assert result == {"service": "ingestion-test", "status": "ok"}
