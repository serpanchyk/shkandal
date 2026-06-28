"""Tests for case-resolution job enqueueing."""

from collections.abc import Sequence
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock
from uuid import uuid4

import pytest
from worker_ml.config import MlConfig
from worker_ml.scripts import enqueue_case_resolution_jobs as script


def _session_context(session: MagicMock) -> MagicMock:
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=None)
    return context


def _scalar_result(values: Sequence[object]) -> MagicMock:
    result = MagicMock()
    result.all.return_value = values
    return result


@pytest.mark.asyncio
async def test_enqueue_case_resolution_uses_configured_batch_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        script,
        "MlConfig",
        lambda: MlConfig(case_resolution_enqueue_batch_size=2),
    )
    session = MagicMock()
    session.scalars = AsyncMock(return_value=_scalar_result([uuid4(), uuid4(), uuid4()]))
    session.scalar = AsyncMock(return_value=0)

    stats = await script.enqueue_case_resolution_jobs(
        Mock(return_value=_session_context(session)),
        apply=False,
    )

    assert stats.selected_cards == 3
    assert session.scalar.await_count == 2


@pytest.mark.asyncio
async def test_enqueue_case_resolution_rejects_non_positive_configured_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        script,
        "MlConfig",
        lambda: SimpleNamespace(job_max_attempts=3, case_resolution_enqueue_batch_size=0),
    )

    with pytest.raises(ValueError, match="batch_size"):
        await script.enqueue_case_resolution_jobs(Mock(), apply=False)
