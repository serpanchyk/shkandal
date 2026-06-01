import pytest
from worker_ml.config import MlConfig
from worker_ml.main import run_once


@pytest.mark.asyncio
async def test_run_once_smoke() -> None:
    result = await run_once(MlConfig(service_name="ml-test"))

    assert result == {"service": "ml-test", "status": "ok"}
