"""Tests for LLM run persistence helpers."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, Mock
from uuid import uuid4

import pytest
from worker_ml.llm.runs import LlmRunStore


@pytest.mark.asyncio
async def test_finish_run_updates_mapped_metadata_attribute() -> None:
    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=None)

    await LlmRunStore(Mock(return_value=session_context)).finish_run(
        run_id=uuid4(),
        status="succeeded",
        metadata={"article_id": str(uuid4())},
    )

    statement = session.execute.await_args.args[0]
    assert statement.compile().params["metadata"] is not None


@pytest.mark.asyncio
async def test_fail_stale_pending_runs_marks_abandoned_runs_failed() -> None:
    session = MagicMock()
    result = MagicMock(rowcount=2)
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=None)

    count = await LlmRunStore(Mock(return_value=session_context)).fail_stale_pending_runs(
        stale_before=datetime(2026, 6, 12, tzinfo=UTC),
    )

    assert count == 2
    statement = session.execute.await_args.args[0]
    assert statement.compile().params["status"] == "failed"
