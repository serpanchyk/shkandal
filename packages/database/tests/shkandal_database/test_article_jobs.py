"""Tests for article job store helpers."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, Mock
from uuid import uuid4

import pytest
from shkandal_database.jobs import ArticleJobStore
from sqlalchemy.dialects.postgresql.base import PGDialect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _mock_session_factory() -> tuple[Mock, MagicMock]:
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=None)
    return Mock(return_value=session_context), session


@pytest.mark.asyncio
async def test_enqueue_article_job_returns_inserted_for_new_job() -> None:
    job_id = uuid4()
    session_factory, session = _mock_session_factory()
    session.scalar = AsyncMock(return_value=job_id)

    result = await ArticleJobStore(session_factory).enqueue_article_job(
        job_type="classify_article",
        article_id=uuid4(),
    )

    assert result.job_id == job_id
    assert result.state == "inserted"


@pytest.mark.parametrize("status", ["queued", "running", "succeeded"])
@pytest.mark.asyncio
async def test_enqueue_article_job_returns_existing_for_untouched_job(status: str) -> None:
    job_id = uuid4()
    session_factory, session = _mock_session_factory()
    session.scalar = AsyncMock(return_value=None)
    existing_result = MagicMock()
    existing_result.one_or_none.return_value = SimpleNamespace(id=job_id, status=status)
    session.execute = AsyncMock(return_value=existing_result)

    result = await ArticleJobStore(session_factory).enqueue_article_job(
        job_type="classify_article",
        article_id=uuid4(),
    )

    assert result.job_id == job_id
    assert result.state == "existing"
    assert session.scalar.await_count == 1


@pytest.mark.asyncio
async def test_enqueue_article_job_requeues_failed_job() -> None:
    job_id = uuid4()
    session_factory, session = _mock_session_factory()
    session.scalar = AsyncMock(side_effect=[None, job_id])
    existing_result = MagicMock()
    existing_result.one_or_none.return_value = SimpleNamespace(id=job_id, status="failed")
    session.execute = AsyncMock(return_value=existing_result)

    result = await ArticleJobStore(session_factory).enqueue_article_job(
        job_type="classify_article",
        article_id=uuid4(),
        max_attempts=5,
    )

    assert result.job_id == job_id
    assert result.state == "requeued"
    requeue_statement = session.scalar.await_args_list[1].args[0]
    assert requeue_statement.compile().params["status"] == "queued"
    assert requeue_statement.compile().params["max_attempts"] == 5


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
