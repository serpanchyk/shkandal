"""Inspect or reset exhausted article fetch failures."""

from __future__ import annotations

import argparse
import asyncio

from shkandal_database.config import DatabaseConfig
from shkandal_database.models import Article, Source
from shkandal_database.session import create_async_engine_from_config, create_async_sessionmaker
from sqlalchemy import select, update


async def reset_failed_fetches(
    *,
    source_slug: str | None,
    limit: int,
    max_attempts: int,
    apply: bool,
) -> tuple[str, ...]:
    """Return exhausted identities and optionally make them immediately retryable."""

    engine = create_async_engine_from_config(DatabaseConfig())
    try:
        session_factory = create_async_sessionmaker(engine)
        async with session_factory() as session:
            statement = (
                select(Article.identity_url)
                .join(Source, Source.id == Article.source_id)
                .where(
                    Article.fetch_status == "failed",
                    Article.fetch_attempt_count >= max_attempts,
                )
                .order_by(Article.updated_at, Article.id)
                .limit(limit)
            )
            if source_slug is not None:
                statement = statement.where(Source.slug == source_slug)
            identity_urls = tuple((await session.scalars(statement)).all())
            if apply and identity_urls:
                await session.execute(
                    update(Article)
                    .where(Article.identity_url.in_(identity_urls))
                    .values(fetch_attempt_count=0, next_fetch_at=None)
                )
                await session.commit()
            return identity_urls
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", dest="source_slug")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--max-attempts", type=int, default=5)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    identity_urls = asyncio.run(
        reset_failed_fetches(
            source_slug=args.source_slug,
            limit=args.limit,
            max_attempts=args.max_attempts,
            apply=args.apply,
        )
    )
    action = "reset" if args.apply else "would reset"
    print(f"{action} {len(identity_urls)} exhausted article fetches")
    for identity_url in identity_urls:
        print(identity_url)


if __name__ == "__main__":
    main()
