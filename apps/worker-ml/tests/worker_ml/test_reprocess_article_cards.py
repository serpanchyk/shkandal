"""Tests for article-card regeneration."""

from collections.abc import Sequence
from unittest.mock import AsyncMock, MagicMock, Mock
from uuid import uuid4

import pytest
from shkandal_database.models import Job
from worker_ml.scripts.reprocess_article_cards import reprocess_article_cards


def _session_context(session: MagicMock) -> MagicMock:
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=None)
    return context


def _scalar_result(values: Sequence[object]) -> MagicMock:
    result = MagicMock()
    result.all.return_value = values
    return result


def _job(*, article_id: object, status: str = "succeeded") -> Job:
    return Job(
        id=uuid4(),
        job_type="create_article_card",
        article_id=article_id,
        status=status,
        payload={},
        attempt_count=2,
        max_attempts=3,
    )


@pytest.mark.asyncio
async def test_reprocess_article_cards_dry_run_reports_without_mutation() -> None:
    existing_id = uuid4()
    missing_id = uuid4()
    session = MagicMock()
    session.scalars = AsyncMock(
        side_effect=[
            _scalar_result([_job(article_id=existing_id)]),
            _scalar_result([existing_id, missing_id]),
        ]
    )
    session.scalar = AsyncMock(return_value=5)
    session.execute = AsyncMock()
    session.commit = AsyncMock()

    stats = await reprocess_article_cards(
        Mock(return_value=_session_context(session)),
        apply=False,
    )

    assert stats.cards_to_delete == 5
    assert stats.jobs_to_reset == 1
    assert stats.jobs_to_create == 1
    session.execute.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_reprocess_article_cards_refuses_running_jobs() -> None:
    session = MagicMock()
    session.scalars = AsyncMock(
        return_value=_scalar_result([_job(article_id=uuid4(), status="running")])
    )

    with pytest.raises(RuntimeError, match="card jobs are running"):
        await reprocess_article_cards(
            Mock(return_value=_session_context(session)),
            apply=True,
        )


@pytest.mark.asyncio
async def test_reprocess_article_cards_applies_reset_and_creates_missing_job() -> None:
    existing_id = uuid4()
    missing_id = uuid4()
    existing_job = _job(article_id=existing_id)
    session = MagicMock()
    session.scalars = AsyncMock(
        side_effect=[
            _scalar_result([existing_job]),
            _scalar_result([existing_id, missing_id]),
        ]
    )
    session.scalar = AsyncMock(return_value=4)
    session.execute = AsyncMock()
    session.commit = AsyncMock()

    stats = await reprocess_article_cards(
        Mock(return_value=_session_context(session)),
        apply=True,
        max_attempts=5,
    )

    assert stats.applied is True
    assert stats.jobs_to_reset == 1
    assert stats.jobs_to_create == 1
    assert session.execute.await_count == 2
    upsert = session.execute.await_args_list[1].args[0]
    params = upsert.compile().params
    assert existing_id in params.values()
    assert missing_id in params.values()
    assert "queued" in params.values()
    assert 5 in params.values()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_reprocess_article_cards_batches_large_job_upserts() -> None:
    article_ids = [uuid4() for _ in range(3)]
    session = MagicMock()
    session.scalars = AsyncMock(
        side_effect=[
            _scalar_result([]),
            _scalar_result(article_ids),
        ]
    )
    session.scalar = AsyncMock(return_value=0)
    session.execute = AsyncMock()
    session.commit = AsyncMock()

    await reprocess_article_cards(
        Mock(return_value=_session_context(session)),
        apply=True,
        job_upsert_batch_size=2,
    )

    assert session.execute.await_count == 3


@pytest.mark.asyncio
async def test_reprocess_article_cards_targets_latest_existing_cards() -> None:
    older_id = uuid4()
    latest_ids = [uuid4(), uuid4()]
    session = MagicMock()
    session.scalars = AsyncMock(
        side_effect=[
            _scalar_result(
                [_job(article_id=older_id), *[_job(article_id=value) for value in latest_ids]]
            ),
            _scalar_result(latest_ids),
        ]
    )
    session.execute = AsyncMock()
    session.commit = AsyncMock()

    stats = await reprocess_article_cards(
        Mock(return_value=_session_context(session)),
        apply=True,
        limit=2,
    )

    assert stats.cards_to_delete == 2
    assert stats.accepted_gate_articles == 2
    assert stats.jobs_to_reset == 2
    delete_statement = session.execute.await_args_list[0].args[0]
    delete_params = delete_statement.compile().params
    assert latest_ids in delete_params.values()
    assert all(older_id not in value for value in delete_params.values() if isinstance(value, list))


@pytest.mark.asyncio
async def test_reprocess_article_cards_rejects_non_positive_limit() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        await reprocess_article_cards(Mock(), apply=False, limit=0)
