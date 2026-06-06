"""Optional continuous-loop ingestion runtime."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from worker_ingestion.config import IngestionConfig
from worker_ingestion.service import IngestionStats

RunOnce = Callable[[], Awaitable[IngestionStats]]


async def run_continuously(
    run_once: RunOnce,
    *,
    config: IngestionConfig,
    logger: logging.Logger,
) -> None:
    """Run optional loop-mode ingestion on a fixed start-to-start cadence."""

    while True:
        started_at = time.monotonic()
        logger.info("worker_ingestion_cycle_started")
        try:
            stats = await run_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("worker_ingestion_cycle_failed")
        else:
            duration_seconds = time.monotonic() - started_at
            logger.info(
                "worker_ingestion_cycle_finished",
                extra={
                    "duration_seconds": duration_seconds,
                    "processed_sources": stats.processed_sources,
                    "failed_sources": stats.failed_sources,
                    "discovered_articles": stats.discovered_articles,
                    "stored_articles": stats.stored_articles,
                    "failed_articles": stats.failed_articles,
                },
            )
            write_heartbeat(config.heartbeat_path)
        elapsed_seconds = time.monotonic() - started_at
        await asyncio.sleep(max(0.0, config.poll_interval_seconds - elapsed_seconds))


def write_heartbeat(path: str) -> None:
    """Record a completed loop-mode pass for the optional healthcheck."""

    heartbeat = Path(path)
    heartbeat.parent.mkdir(parents=True, exist_ok=True)
    heartbeat.write_text(str(time.time()), encoding="ascii")


def heartbeat_is_fresh(path: str, *, max_age_seconds: int) -> bool:
    """Return whether a completed ingestion pass was recorded recently."""

    try:
        completed_at = float(Path(path).read_text(encoding="ascii"))
    except (OSError, ValueError):
        return False
    return time.time() - completed_at <= max_age_seconds
