"""Tests for exhausted worker-job recovery."""

from collections.abc import Sequence
from unittest.mock import AsyncMock, MagicMock, Mock
from uuid import uuid4

import pytest
from worker_ml.scripts.recover_failed_jobs import recover_failed_jobs


def _session_context(session: MagicMock) -> MagicMock:
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=None)
    return context


def _scalar_result(values: Sequence[object]) -> MagicMock:
    result = MagicMock()
    result.all.return_value = values
    return result


async def test_recover_failed_jobs_is_dry_run_by_default_behavior() -> None:
    job_ids = [uuid4(), uuid4()]
    session = MagicMock()
    session.scalars = AsyncMock(return_value=_scalar_result(job_ids))
    session.execute = AsyncMock()
    session.commit = AsyncMock()

    stats = await recover_failed_jobs(
        Mock(return_value=_session_context(session)),
        job_type="update_case_copy",
        apply=False,
    )

    assert stats.selected_job_ids == tuple(job_ids)
    assert stats.applied is False
    session.execute.assert_not_awaited()
    session.commit.assert_not_awaited()
    query = session.scalars.await_args.args[0]
    assert "jobs.status =" in str(query)
    assert "jobs.attempt_count >= jobs.max_attempts" in str(query)


async def test_recover_failed_jobs_applies_filters_and_resets_only_selected_jobs() -> None:
    selected_id = uuid4()
    session = MagicMock()
    session.scalars = AsyncMock(return_value=_scalar_result([selected_id]))
    session.execute = AsyncMock()
    session.commit = AsyncMock()

    stats = await recover_failed_jobs(
        Mock(return_value=_session_context(session)),
        job_type="update_case_copy",
        error_contains="Qdrant",
        limit=12,
        apply=True,
    )

    assert stats.selected_jobs == 1
    selection = session.scalars.await_args.args[0]
    assert "last_error LIKE" in str(selection)
    assert "LIMIT" in str(selection)
    reset = session.execute.await_args.args[0]
    params = reset.compile().params
    assert [selected_id] in params.values()
    assert params["status"] == "queued"
    assert params["attempt_count"] == 0
    assert params["last_error"] is None
    session.commit.assert_awaited_once()


@pytest.mark.parametrize("limit", [0, -1])
async def test_recover_failed_jobs_rejects_non_positive_limit(limit: int) -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        await recover_failed_jobs(Mock(), job_type="update_case_copy", apply=False, limit=limit)
