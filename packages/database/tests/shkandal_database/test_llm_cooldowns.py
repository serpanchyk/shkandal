"""Tests for durable shared LLM cooldown state."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from shkandal_database.llm_cooldowns import LlmCooldownStore


def _mock_session_factory() -> tuple[Mock, MagicMock]:
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=None)
    return Mock(return_value=session_context), session


@pytest.mark.asyncio
async def test_active_resume_at_ignores_expired_cooldown() -> None:
    now = datetime(2026, 6, 8, 14, 0, tzinfo=UTC)
    session_factory, session = _mock_session_factory()
    session.scalar = AsyncMock(return_value=now - timedelta(seconds=1))

    assert await LlmCooldownStore(session_factory).active_resume_at(now=now) is None


@pytest.mark.asyncio
async def test_extend_keeps_existing_later_cooldown() -> None:
    session_factory, session = _mock_session_factory()
    later = datetime(2026, 6, 8, 16, 0, tzinfo=UTC)
    session.scalar = AsyncMock(side_effect=[None, later])

    result = await LlmCooldownStore(session_factory).extend(
        resume_at=datetime(2026, 6, 8, 15, 0, tzinfo=UTC),
        reason="rate limit",
    )

    assert result == later
    statement = session.scalar.await_args_list[0].args[0]
    assert "llm_cooldowns.resume_at <" in str(statement)
