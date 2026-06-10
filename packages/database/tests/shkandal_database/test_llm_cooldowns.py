"""Tests for durable shared LLM cooldown state."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from shkandal_database.llm_cooldowns import LlmCooldownStore
from shkandal_database.models import LlmCooldown


def _mock_session_factory(*, existing: LlmCooldown | None = None) -> tuple[Mock, MagicMock]:
    session = MagicMock()
    session.scalar = AsyncMock(return_value=existing)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=None)
    return Mock(return_value=session_context), session


def _cooldown(
    *,
    resume_at: datetime,
    count: int,
    observed_at: datetime | None,
    kind: str = "ambiguous_short",
) -> LlmCooldown:
    return LlmCooldown(
        scope="shared-provider",
        resume_at=resume_at,
        reason="rate limit",
        cooldown_kind=kind,
        ambiguous_observation_count=count,
        last_ambiguous_observed_at=observed_at,
    )


@pytest.mark.asyncio
async def test_active_resume_at_ignores_expired_cooldown() -> None:
    now = datetime(2026, 6, 8, 14, 0, tzinfo=UTC)
    session_factory, session = _mock_session_factory()
    session.scalar = AsyncMock(return_value=now - timedelta(seconds=1))

    assert await LlmCooldownStore(session_factory).active_resume_at(now=now) is None


@pytest.mark.asyncio
async def test_first_ambiguous_rate_limit_creates_five_minute_cooldown() -> None:
    now = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)
    session_factory, session = _mock_session_factory()

    result = await LlmCooldownStore(session_factory).record_rate_limit(
        retry_after_seconds=None,
        reason="ambiguous 429",
        observed_at=now,
    )

    assert result.resume_at == now + timedelta(minutes=5)
    assert result.kind == "ambiguous_short"
    assert result.ambiguous_observation_count == 1
    session.add.assert_called_once()


@pytest.mark.asyncio
async def test_second_ambiguous_rate_limit_within_window_creates_hourly_cooldown() -> None:
    now = datetime(2026, 6, 10, 12, 10, tzinfo=UTC)
    existing = _cooldown(
        resume_at=now - timedelta(minutes=5),
        count=1,
        observed_at=now - timedelta(minutes=10),
    )
    session_factory, _ = _mock_session_factory(existing=existing)

    result = await LlmCooldownStore(session_factory).record_rate_limit(
        retry_after_seconds=None,
        reason="second ambiguous 429",
        observed_at=now,
    )

    assert result.resume_at == now + timedelta(hours=1)
    assert result.kind == "inferred_hourly"
    assert result.ambiguous_observation_count == 2


@pytest.mark.asyncio
async def test_old_ambiguous_observation_resets_to_first_observation() -> None:
    now = datetime(2026, 6, 10, 13, 0, tzinfo=UTC)
    existing = _cooldown(
        resume_at=now - timedelta(minutes=30),
        count=2,
        observed_at=now - timedelta(minutes=16),
        kind="inferred_hourly",
    )
    session_factory, _ = _mock_session_factory(existing=existing)

    result = await LlmCooldownStore(session_factory).record_rate_limit(
        retry_after_seconds=None,
        reason="new ambiguous 429",
        observed_at=now,
    )

    assert result.kind == "ambiguous_short"
    assert result.ambiguous_observation_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("retry_after_seconds", "kind"),
    [(120, "provider_short"), (1800, "provider_long")],
)
async def test_retry_after_classifies_provider_cooldown(
    retry_after_seconds: int,
    kind: str,
) -> None:
    now = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)
    session_factory, _ = _mock_session_factory()

    result = await LlmCooldownStore(session_factory).record_rate_limit(
        retry_after_seconds=retry_after_seconds,
        reason="explicit 429",
        observed_at=now,
    )

    assert result.kind == kind
    assert result.resume_at == now + timedelta(seconds=retry_after_seconds)


@pytest.mark.asyncio
async def test_success_clears_expired_ambiguous_observation() -> None:
    now = datetime(2026, 6, 10, 13, 0, tzinfo=UTC)
    session_factory, session = _mock_session_factory()

    await LlmCooldownStore(session_factory).clear_expired_ambiguous_observation(now=now)

    statement = session.execute.await_args.args[0]
    assert "ambiguous_observation_count" in str(statement)
    assert "llm_cooldowns.resume_at <=" in str(statement)
