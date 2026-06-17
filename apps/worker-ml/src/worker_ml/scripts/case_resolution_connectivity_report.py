"""Generate a read-only Case-resolution connectivity report from PostgreSQL."""

from __future__ import annotations

import argparse
import asyncio

from shkandal_database.config import DatabaseConfig
from shkandal_database.session import create_async_engine_from_config, create_async_sessionmaker

from worker_ml.cases.connectivity_report import (
    load_case_resolution_connectivity_report,
    render_case_resolution_connectivity_report,
)


def main() -> None:
    """Run the Case-resolution connectivity report CLI."""

    parser = argparse.ArgumentParser(
        description="Report case-candidate articles that completed Case resolution without links."
    )
    parser.add_argument(
        "--example-limit",
        type=int,
        default=20,
        help="Maximum number of recent unconnected example articles to show.",
    )
    args = parser.parse_args()

    asyncio.run(_run(example_limit=args.example_limit))


async def _run(*, example_limit: int) -> None:
    engine = create_async_engine_from_config(DatabaseConfig())
    try:
        report = await load_case_resolution_connectivity_report(
            create_async_sessionmaker(engine),
            example_limit=example_limit,
        )
        print(render_case_resolution_connectivity_report(report), end="")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    main()
