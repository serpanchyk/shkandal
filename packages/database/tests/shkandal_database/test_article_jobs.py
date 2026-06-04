"""Tests for article job store helpers."""

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from shkandal_database.jobs import ArticleJobStore
from sqlalchemy.dialects.postgresql.base import PGDialect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def test_retry_delay_uses_configured_backoff_without_jitter() -> None:
    session_factory = cast(async_sessionmaker[AsyncSession], object())
    store = ArticleJobStore(
        session_factory=session_factory,
        retry_jitter_ratio=0,
    )

    assert store.retry_delay(1) == timedelta(minutes=1)
    assert store.retry_delay(2) == timedelta(minutes=5)
    assert store.retry_delay(3) == timedelta(minutes=15)
    assert store.retry_delay(4) == timedelta(minutes=15)


def test_claim_query_uses_skip_locked() -> None:
    now = datetime(2026, 6, 4, 12, 0, tzinfo=UTC)
    statement = ArticleJobStore._eligible_job_id_query(
        stale_before=now - timedelta(minutes=30),
        now=now,
        job_types=("classify_article",),
    ).with_for_update(skip_locked=True)

    dialect_factory = cast(Any, PGDialect)
    compiled = str(statement.compile(dialect=dialect_factory()))

    assert "FOR UPDATE SKIP LOCKED" in compiled
    assert "jobs.job_type IN" in compiled
