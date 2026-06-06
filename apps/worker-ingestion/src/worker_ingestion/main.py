"""Ingestion worker process entrypoint."""

import argparse
import asyncio
from datetime import datetime, time

from shkandal_common.logging import setup_logger
from shkandal_database.config import DatabaseConfig
from shkandal_database.session import create_async_engine_from_config, create_async_sessionmaker

from worker_ingestion.config import IngestionConfig
from worker_ingestion.maintenance.repair import PublishedAtRepairStats, repair_missing_published_at
from worker_ingestion.persistence.articles import SqlAlchemyArticleRepository
from worker_ingestion.runtime import run_continuously
from worker_ingestion.service import IngestionStats, IngestionWorker
from worker_ingestion.transport import HttpxFetcher


async def run_once(
    config: IngestionConfig | None = None,
    *,
    source_slug: str | None = None,
    limit: int | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    max_backfill_urls_per_source: int | None = None,
) -> IngestionStats:
    settings = config or IngestionConfig()
    if max_backfill_urls_per_source is not None:
        settings.max_backfill_urls_per_source = max_backfill_urls_per_source
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
                "failed_sources": stats.failed_sources,
                "discovered_articles": stats.discovered_articles,
                "skipped_existing_articles": stats.skipped_existing_articles,
                "skipped_out_of_window_articles": stats.skipped_out_of_window_articles,
                "stored_articles": stats.stored_articles,
                "failed_articles": stats.failed_articles,
            },
        )
        return stats
    finally:
        await engine.dispose()


async def repair_published_at(
    config: IngestionConfig | None = None,
    *,
    source_slug: str | None = None,
    limit: int | None = None,
    batch_size: int = 500,
    apply: bool = False,
) -> PublishedAtRepairStats:
    settings = config or IngestionConfig()
    logger = setup_logger(settings.service_name)
    logger.info(
        "worker_ingestion_published_at_repair_started",
        extra={
            "source_slug": source_slug,
            "limit": limit,
            "batch_size": batch_size,
            "apply": apply,
        },
    )
    engine = create_async_engine_from_config(
        DatabaseConfig(database_url=settings.postgres_database_url)
    )
    try:
        repository = SqlAlchemyArticleRepository(create_async_sessionmaker(engine))
        stats = await repair_missing_published_at(
            repository,
            apply=apply,
            source_slug=source_slug,
            limit=limit,
            batch_size=batch_size,
        )
        logger.info(
            "worker_ingestion_published_at_repair_finished",
            extra={
                "scanned_articles": stats.scanned_articles,
                "repairable_articles": stats.repairable_articles,
                "updated_articles": stats.updated_articles,
                "apply": apply,
            },
        )
        return stats
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Shkandal source ingestion.")
    parser.add_argument(
        "--once",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Run ingestion continuously instead of exiting after one pass.",
    )
    parser.add_argument("--source", dest="source_slug")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--since", type=_parse_since_datetime)
    parser.add_argument("--until", type=_parse_until_datetime)
    parser.add_argument(
        "--max-backfill-urls-per-source",
        type=int,
        help="Override date-bounded discovery cap for dense source backfills.",
    )
    parser.add_argument(
        "--repair-missing-published-at",
        action="store_true",
        help="Repair missing published_at from stored raw_html without refetching.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply repair changes. Repair mode is dry-run unless this is set.",
    )
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args()
    if args.repair_missing_published_at:
        asyncio.run(
            repair_published_at(
                source_slug=args.source_slug,
                limit=args.limit,
                batch_size=args.batch_size,
                apply=args.apply,
            )
        )
        return

    if args.loop:
        settings = IngestionConfig()
        logger = setup_logger(settings.service_name)
        asyncio.run(
            run_continuously(
                lambda: run_once(settings),
                config=settings,
                logger=logger,
            )
        )
        return

    asyncio.run(
        run_once(
            source_slug=args.source_slug,
            limit=args.limit,
            since=args.since,
            until=args.until,
            max_backfill_urls_per_source=args.max_backfill_urls_per_source,
        )
    )


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _parse_since_datetime(value: str) -> datetime:
    return _parse_datetime(value)


def _parse_until_datetime(value: str) -> datetime:
    if "T" in value:
        return _parse_datetime(value)
    return datetime.combine(datetime.fromisoformat(value).date(), time.max)


if __name__ == "__main__":
    main()
