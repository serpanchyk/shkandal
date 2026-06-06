import asyncio
import logging
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from worker_ingestion.config import IngestionConfig
from worker_ingestion.runtime import heartbeat_is_fresh, run_continuously
from worker_ingestion.service import IngestionStats


@pytest.mark.asyncio
async def test_continuous_runtime_records_completed_cycle_and_sleeps(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls = 0
    sleep_intervals: list[float] = []

    async def run_once() -> IngestionStats:
        nonlocal calls
        calls += 1
        return IngestionStats(processed_sources=2, failed_sources=1)

    async def stop_after_sleep(interval: float) -> None:
        sleep_intervals.append(interval)
        raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "sleep", stop_after_sleep)
    monotonic_values = iter((100.0, 110.0, 110.0))
    monkeypatch.setattr(
        "worker_ingestion.runtime.time",
        SimpleNamespace(monotonic=lambda: next(monotonic_values), time=time.time),
    )
    heartbeat_path = tmp_path / "heartbeat"
    config = IngestionConfig(
        poll_interval_seconds=3600,
        heartbeat_path=str(heartbeat_path),
    )

    with pytest.raises(asyncio.CancelledError):
        await run_continuously(run_once, config=config, logger=logging.getLogger("test"))

    assert calls == 1
    assert sleep_intervals == [3590]
    assert heartbeat_is_fresh(str(heartbeat_path), max_age_seconds=60)


def test_missing_heartbeat_is_unhealthy(tmp_path: Path) -> None:
    assert not heartbeat_is_fresh(str(tmp_path / "missing"), max_age_seconds=60)
