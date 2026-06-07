"""Tests for LLM run persistence helpers."""

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
