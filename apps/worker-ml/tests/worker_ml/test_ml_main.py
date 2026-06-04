import pytest
from worker_ml.config import MlConfig
from worker_ml.main import run_once


@pytest.mark.asyncio
async def test_run_once_smoke() -> None:
    result = await run_once(MlConfig(service_name="ml-test"))

    assert result == {"service": "ml-test", "status": "ok"}


def test_stale_job_timeout_config() -> None:
    config = MlConfig(stale_job_timeout_seconds=60)

    assert config.stale_job_timeout.total_seconds() == 60
