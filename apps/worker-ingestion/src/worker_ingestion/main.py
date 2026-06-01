"""Ingestion worker process entrypoint."""

import asyncio

from shkandal_common.logging import setup_logger

from worker_ingestion.config import IngestionConfig


async def run_once(config: IngestionConfig | None = None) -> dict[str, str]:
    settings = config or IngestionConfig()
    logger = setup_logger(settings.service_name)
    logger.info(
        "worker_ready",
        extra={
            "service": settings.service_name,
            "poll_interval_seconds": settings.poll_interval_seconds,
        },
    )
    return {"service": settings.service_name, "status": "ok"}


def main() -> None:
    asyncio.run(run_once())


if __name__ == "__main__":
    main()
