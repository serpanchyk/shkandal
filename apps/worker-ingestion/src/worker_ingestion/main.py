"""Ingestion worker process entrypoint."""

import argparse
import asyncio
from datetime import datetime

from shkandal_common.logging import setup_logger
from shkandal_database.config import DatabaseConfig
from shkandal_database.session import create_async_engine_from_config, create_async_sessionmaker

from worker_ingestion.config import IngestionConfig
from worker_ingestion.service import IngestionStats, IngestionWorker
from worker_ingestion.storage import SqlAlchemyArticleRepository
from worker_ingestion.transport import HttpxFetcher


async def run_once(
    config: IngestionConfig | None = None,
    *,
    source_slug: str | None = None,
    limit: int | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> IngestionStats:
    settings = config or IngestionConfig()
    logger = setup_logger(settings.service_name)
    logger.info(
        "worker_ingestion_started",
        extra={
            "service": settings.service_name,
            "poll_interval_seconds": settings.poll_interval_seconds,
            "source_slug": source_slug,
            "limit": limit,
        },
    )
    engine = create_async_engine_from_config(
        DatabaseConfig(database_url=settings.postgres_database_url)
    )
    try:
        repository = SqlAlchemyArticleRepository(create_async_sessionmaker(engine))
        worker = IngestionWorker(
            config=settings,
            fetcher=HttpxFetcher(settings),
            repository=repository,
        )
        stats = await worker.run_once(
            source_slug=source_slug,
            limit=limit,
            since=since,
            until=until,
        )
        logger.info(
            "worker_ingestion_finished",
            extra={
                "processed_sources": stats.processed_sources,
                "discovered_articles": stats.discovered_articles,
                "stored_articles": stats.stored_articles,
                "failed_articles": stats.failed_articles,
            },
        )
        return stats
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Shkandal media ingestion.")
    parser.add_argument("--source", dest="source_slug")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--since", type=_parse_datetime)
    parser.add_argument("--until", type=_parse_datetime)
    args = parser.parse_args()
    asyncio.run(
        run_once(
            source_slug=args.source_slug,
            limit=args.limit,
            since=args.since,
            until=args.until,
        )
    )


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


if __name__ == "__main__":
    main()
