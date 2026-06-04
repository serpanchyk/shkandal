"""ML worker process entrypoint."""

import asyncio

from shkandal_common.logging import setup_logger
from shkandal_database.config import DatabaseConfig
from shkandal_database.jobs import ArticleJobStore
from shkandal_database.session import create_async_engine_from_config, create_async_sessionmaker

from worker_ml.config import MlConfig
from worker_ml.jobs import MlJobPlanner


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


async def enqueue_missing_classification_jobs(config: MlConfig | None = None) -> dict[str, int]:
    """Run one ML enqueue pass for articles missing classifier output."""

    settings = config or MlConfig()
    logger = setup_logger(settings.service_name)
    engine = create_async_engine_from_config(
        DatabaseConfig(database_url=settings.postgres_database_url)
    )
    try:
        session_factory = create_async_sessionmaker(engine)
        job_store = ArticleJobStore(
            session_factory,
            stale_job_timeout=settings.stale_job_timeout,
        )
        planner = MlJobPlanner(session_factory, job_store)
        stats = await planner.enqueue_missing_classification_jobs(
            limit=settings.enqueue_batch_size,
            max_attempts=settings.job_max_attempts,
        )
        logger.info(
            "worker_ml_jobs_enqueued",
            extra={
                "scanned_articles": stats.scanned_articles,
                "ensured_jobs": stats.ensured_jobs,
                "job_type": "classify_article",
            },
        )
        return {
            "scanned_articles": stats.scanned_articles,
            "ensured_jobs": stats.ensured_jobs,
        }
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(run_once())


if __name__ == "__main__":
    main()
