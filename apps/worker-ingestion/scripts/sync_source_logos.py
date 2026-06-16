"""Discover Source website icons and synchronize frontend-owned PNG assets."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
from pathlib import Path

from shkandal_common.logging import setup_logger
from shkandal_database.config import DatabaseConfig
from shkandal_database.session import create_async_engine_from_config, create_async_sessionmaker
from worker_ingestion.config import IngestionConfig
from worker_ingestion.source_logos import SqlAlchemySourceLogoRepository, sync_source_logos
from worker_ingestion.transport import HttpxFetcher

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "apps/frontend/public/sources"


async def run(*, source_slug: str | None, apply: bool, timeout: float) -> int:
    """Run Source logo synchronization and return a process exit code."""

    settings = IngestionConfig(request_timeout_seconds=timeout)
    logger = setup_logger("source-logo-sync")
    engine = create_async_engine_from_config(DatabaseConfig())
    try:
        results = await sync_source_logos(
            SqlAlchemySourceLogoRepository(create_async_sessionmaker(engine)),
            HttpxFetcher(settings),
            output_dir=DEFAULT_OUTPUT_DIR,
            apply=apply,
            source_slug=source_slug,
        )
    finally:
        await engine.dispose()

    for result in results:
        logger.info("source_logo_sync_result", extra=asdict(result) | {"apply": apply})
    failed_sources = sum(result.status == "failed" for result in results)
    logger.info(
        "source_logo_sync_finished",
        extra={
            "apply": apply,
            "processed_sources": len(results),
            "failed_sources": failed_sources,
        },
    )
    return 1 if failed_sources else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", dest="source_slug", help="Limit synchronization to one slug.")
    parser.add_argument("--timeout", type=float, default=20.0, help="Request timeout in seconds.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Overwrite PNG assets and update Source.logo_path.",
    )
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(run(source_slug=args.source_slug, apply=args.apply, timeout=args.timeout))
    )


if __name__ == "__main__":
    main()
