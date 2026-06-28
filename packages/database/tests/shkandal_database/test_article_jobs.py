"""Tests for article job store helpers."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, Mock
from uuid import uuid4

import pytest
from shkandal_database.jobs import ArticleJobStore, JobQueueSummary
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


@pytest.mark.asyncio
async def test_bulk_enqueue_article_jobs_counts_states_in_one_transaction() -> None:
    article_ids = [uuid4(), uuid4(), uuid4()]
    session_factory, session = _mock_session_factory()
    session.scalars = AsyncMock(
        side_effect=[
            SimpleNamespace(all=lambda: [article_ids[0]]),
            SimpleNamespace(all=lambda: [article_ids[1]]),
        ]
    )

    result = await ArticleJobStore(session_factory).enqueue_article_jobs(
        job_type="classify_article",
        article_ids=article_ids,
    )

    assert result.inserted_jobs == 1
    assert result.requeued_jobs == 1
    assert result.existing_jobs == 1
    assert session.scalars.await_count == 2


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
    assert requeue_statement.compile().params["attempt_count"] == 0
    assert requeue_statement.compile().params["max_attempts"] == 5


@pytest.mark.asyncio
async def test_enqueue_article_job_can_leave_failed_job_exhausted() -> None:
    job_id = uuid4()
    session_factory, session = _mock_session_factory()
    session.scalar = AsyncMock(return_value=None)
    existing_result = MagicMock()
    existing_result.one_or_none.return_value = SimpleNamespace(id=job_id, status="failed")
    session.execute = AsyncMock(return_value=existing_result)

    result = await ArticleJobStore(session_factory).enqueue_article_job(
        job_type="classify_article",
        article_id=uuid4(),
        requeue_failed=False,
    )

    assert result.state == "existing"
    assert session.scalar.await_count == 1
    assert session.execute.await_count == 1


@pytest.mark.asyncio
async def test_summarize_jobs_returns_selected_queue_state() -> None:
    next_run_after = datetime(2026, 6, 11, 18, 0, tzinfo=UTC)
    session_factory, session = _mock_session_factory()
    result = MagicMock()
    result.one.return_value = (3, 2, 1, 4, next_run_after, 1)
    session.execute = AsyncMock(return_value=result)

    summary = await ArticleJobStore(session_factory).summarize_jobs(
        job_types=("classify_article", "create_article_card")
    )

    assert summary == JobQueueSummary(
        queued_jobs=3,
        running_jobs=2,
        blocked_jobs=1,
        failed_jobs=4,
        next_run_after=next_run_after,
        blocked_running_jobs=1,
    )
    statement = session.execute.await_args.args[0]
    assert "jobs.job_type IN" in str(statement)
    assert "jobs.attempt_count < jobs.max_attempts" in str(statement)
    assert "jobs.attempt_count >= jobs.max_attempts" in str(statement)


def test_article_job_claims_are_ordered_by_article_publication_date() -> None:
    query = ArticleJobStore._eligible_job_id_query(
        stale_before=datetime(2026, 6, 11, 17, 30, tzinfo=UTC),
        now=datetime(2026, 6, 11, 18, 0, tzinfo=UTC),
        job_types=("create_article_card",),
    )

    query_text = str(query)

    assert "articles.published_at" in query_text
    assert "NULLS LAST" in query_text
    assert query_text.index("articles.published_at") < query_text.index("jobs.created_at")


@pytest.mark.asyncio
async def test_enqueue_case_job_requests_another_revision() -> None:
    job_id = uuid4()
    case_id = uuid4()
    session_factory, session = _mock_session_factory()
    session.scalar = AsyncMock(return_value=None)
    existing_result = MagicMock()
    existing_result.one_or_none.return_value = SimpleNamespace(id=job_id, status="running")
    session.execute = AsyncMock(return_value=existing_result)

    result = await ArticleJobStore(session_factory).enqueue_case_job(
        job_type="refresh_case",
        case_id=case_id,
    )

    assert result.state == "requeued"
    statement = session.execute.await_args_list[1].args[0]
    assert "requested_revision + " in str(statement)
    assert statement.compile().params["status"] == "running"


@pytest.mark.parametrize("status", ["queued", "succeeded", "failed"])
@pytest.mark.asyncio
async def test_enqueue_case_job_gives_non_running_revision_fresh_attempts(status: str) -> None:
    job_id = uuid4()
    session_factory, session = _mock_session_factory()
    session.scalar = AsyncMock(return_value=None)
    existing_result = MagicMock()
    existing_result.one_or_none.return_value = SimpleNamespace(id=job_id, status=status)
    session.execute = AsyncMock(return_value=existing_result)

    await ArticleJobStore(session_factory).enqueue_case_job(
        job_type="refresh_case",
        case_id=uuid4(),
    )

    statement = session.execute.await_args_list[1].args[0]
    params = statement.compile().params
    assert params["status"] == "queued"
    assert params["attempt_count"] == 0
    assert params["last_error"] is None


@pytest.mark.asyncio
async def test_ensure_case_job_requeues_completed_recurring_job_without_revision() -> None:
    job_id = uuid4()
    session_factory, session = _mock_session_factory()
    session.scalar = AsyncMock(side_effect=[None, job_id])
    existing_result = MagicMock()
    existing_result.one_or_none.return_value = SimpleNamespace(id=job_id, status="succeeded")
    session.execute = AsyncMock(return_value=existing_result)

    result = await ArticleJobStore(session_factory).ensure_case_job(
        job_type="audit_case_coherence",
        case_id=uuid4(),
    )

    assert result.state == "requeued"
    statement = session.scalar.await_args_list[1].args[0]
    params = statement.compile().params
    assert params["status"] == "queued"
    assert "requested_revision" not in params


@pytest.mark.asyncio
async def test_complete_superseded_revision_requeues_with_fresh_attempts() -> None:
    session_factory, session = _mock_session_factory()
    session.execute = AsyncMock()

    await ArticleJobStore(session_factory).complete_job(
        job_id=uuid4(),
        processed_revision=2,
    )

    statement = session.execute.await_args.args[0]
    assert "requested_revision > " in str(statement)
    assert "attempt_count" in str(statement)


@pytest.mark.asyncio
async def test_fail_superseded_revision_requeues_with_fresh_attempts() -> None:
    session_factory, session = _mock_session_factory()
    session.execute = AsyncMock()

    await ArticleJobStore(session_factory).fail_job(
        job_id=uuid4(),
        error_message="invalid output",
        attempt_count=3,
        max_attempts=3,
        processed_revision=2,
    )

    statement = session.execute.await_args.args[0]
    assert "requested_revision > " in str(statement)
    assert "attempt_count" in str(statement)


@pytest.mark.asyncio
async def test_fail_job_never_persists_an_empty_error() -> None:
    session_factory, session = _mock_session_factory()
    session.execute = AsyncMock()

    await ArticleJobStore(session_factory).fail_job(
        job_id=uuid4(),
        error_message="",
        attempt_count=3,
        max_attempts=3,
    )

    statement = session.execute.await_args.args[0]
    assert statement.compile().params["last_error"] == "UnknownError"


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
    assert "jobs.attempt_count < jobs.max_attempts" in compiled


@pytest.mark.asyncio
async def test_defer_job_releases_claim_and_restores_attempt() -> None:
    session_factory, session = _mock_session_factory()
    session.execute = AsyncMock()
    resume_at = datetime(2026, 6, 8, 15, 0, tzinfo=UTC)

    await ArticleJobStore(session_factory).defer_job(
        job_id=uuid4(),
        run_after=resume_at,
        reason="LLM rate limit",
    )

    statement = session.execute.await_args.args[0]
    params = statement.compile().params
    assert params["status"] == "queued"
    assert params["run_after"] == resume_at
    assert params["last_error"] == "LLM rate limit"
    assert "attempt_count - " in str(statement)
