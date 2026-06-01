"""ML worker process entrypoint."""

import asyncio

from shkandal_common.logging import setup_logger

from worker_ml.config import MlConfig


async def run_once(config: MlConfig | None = None) -> dict[str, str]:
    settings = config or MlConfig()
    logger = setup_logger(settings.service_name)
    logger.info(
        "worker_ready",
        extra={
            "service": settings.service_name,
            "poll_interval_seconds": settings.poll_interval_seconds,
            "qdrant_url": settings.qdrant_url,
        },
    )
    return {"service": settings.service_name, "status": "ok"}


def main() -> None:
    asyncio.run(run_once())


if __name__ == "__main__":
    main()
