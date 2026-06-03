"""Generate a read-only article coverage report from PostgreSQL."""

from __future__ import annotations

import argparse
import asyncio
from datetime import date

from shkandal_database.config import DatabaseConfig
from shkandal_database.session import create_async_engine_from_config, create_async_sessionmaker
from worker_ingestion.article_coverage import (
    CoverageGroupBy,
    load_article_coverage_report,
    render_article_coverage_markdown,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Report stored article coverage by source and date period."
    )
    parser.add_argument("--source", dest="source_slug", help="Limit the report to one source slug.")
    parser.add_argument(
        "--group-by",
        choices=[group_by.value for group_by in CoverageGroupBy],
        default=CoverageGroupBy.MONTH.value,
        help="Date period granularity.",
    )
    parser.add_argument("--since", type=date.fromisoformat, help="Expected coverage start date.")
    parser.add_argument("--until", type=date.fromisoformat, help="Expected coverage end date.")
    args = parser.parse_args()

    asyncio.run(
        _run(
            source_slug=args.source_slug,
            group_by=CoverageGroupBy(args.group_by),
            since=args.since,
            until=args.until,
        )
    )


async def _run(
    *,
    source_slug: str | None,
    group_by: CoverageGroupBy,
    since: date | None,
    until: date | None,
) -> None:
    engine = create_async_engine_from_config(DatabaseConfig())
    try:
        report = await load_article_coverage_report(
            create_async_sessionmaker(engine),
            source_slug=source_slug,
            group_by=group_by,
            since=since,
            until=until,
        )
        print(render_article_coverage_markdown(report), end="")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    main()
