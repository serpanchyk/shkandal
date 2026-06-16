"""PostgreSQL-backed shared LLM cooldown state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from shkandal_database.models import LlmCooldown
from shkandal_database.session import async_session_scope

DEFAULT_LLM_COOLDOWN_SCOPE = "shared-provider"
LONG_RETRY_AFTER_THRESHOLD = timedelta(minutes=30)
AMBIGUOUS_COOLDOWN = timedelta(minutes=5)
AMBIGUOUS_OBSERVATION_WINDOW = timedelta(minutes=15)
INFERRED_HOURLY_COOLDOWN = timedelta(hours=1)


@dataclass(frozen=True)
class LlmCooldownDecision:
    """Persisted cooldown selected for one provider rate-limit response."""

    resume_at: datetime
    kind: str
    ambiguous_observation_count: int


class LlmCooldownStore:
    """Read and update the shared pause applied to all ML processing."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        scope: str = DEFAULT_LLM_COOLDOWN_SCOPE,
    ) -> None:
        self._session_factory = session_factory
        self._scope = scope

    async def active_resume_at(self, *, now: datetime | None = None) -> datetime | None:
        """Return the active cooldown expiry, if any."""

        checked_at = now or datetime.now(UTC)
        async with self._session_factory() as session:
            resume_at = await session.scalar(
                select(LlmCooldown.resume_at).where(LlmCooldown.scope == self._scope)
            )
        if resume_at is None or resume_at <= checked_at:
            return None
        return resume_at

    async def record_rate_limit(
        self,
        *,
        retry_after_seconds: int | None,
        reason: str,
        observed_at: datetime | None = None,
    ) -> LlmCooldownDecision:
        """Classify and persist one HTTP 429 observation."""

        observed = observed_at or datetime.now(UTC)
        async with async_session_scope(self._session_factory) as session:
            await session.execute(select(func.pg_advisory_xact_lock(func.hashtext(self._scope))))
            existing = await session.scalar(
                select(LlmCooldown).where(LlmCooldown.scope == self._scope).with_for_update()
            )
            if retry_after_seconds is not None:
                duration = timedelta(seconds=retry_after_seconds)
                kind = (
                    "provider_short" if duration < LONG_RETRY_AFTER_THRESHOLD else "provider_long"
                )
                count = 0
                last_ambiguous_observed_at = None
            else:
                previous_observation = (
                    existing.last_ambiguous_observed_at if existing is not None else None
                )
                previous_count = existing.ambiguous_observation_count if existing is not None else 0
                if (
                    previous_observation is not None
                    and previous_observation >= observed - AMBIGUOUS_OBSERVATION_WINDOW
                    and previous_count >= 1
                ):
                    duration = INFERRED_HOURLY_COOLDOWN
                    kind = "inferred_hourly"
                    count = previous_count + 1
                else:
                    duration = AMBIGUOUS_COOLDOWN
                    kind = "ambiguous_short"
                    count = 1
                last_ambiguous_observed_at = observed

            requested_resume_at = observed + duration
            resume_at = max(
                requested_resume_at,
                existing.resume_at if existing is not None else requested_resume_at,
            )
            if existing is None:
                session.add(
                    LlmCooldown(
                        scope=self._scope,
                        resume_at=resume_at,
                        reason=reason,
                        cooldown_kind=kind,
                        ambiguous_observation_count=count,
                        last_ambiguous_observed_at=last_ambiguous_observed_at,
                        updated_at=observed,
                    )
                )
            else:
                existing.resume_at = resume_at
                existing.reason = reason
                existing.cooldown_kind = kind
                existing.ambiguous_observation_count = count
                existing.last_ambiguous_observed_at = last_ambiguous_observed_at
                existing.updated_at = observed
        return LlmCooldownDecision(
            resume_at=resume_at,
            kind=kind,
            ambiguous_observation_count=count,
        )

    async def clear_expired_ambiguous_observation(
        self,
        *,
        now: datetime | None = None,
    ) -> None:
        """Clear stale ambiguous-429 evidence after a successful LLM request."""

        succeeded_at = now or datetime.now(UTC)
        async with async_session_scope(self._session_factory) as session:
            await session.execute(
                update(LlmCooldown)
                .where(
                    LlmCooldown.scope == self._scope,
                    LlmCooldown.resume_at <= succeeded_at,
                    LlmCooldown.last_ambiguous_observed_at.is_not(None),
                )
                .values(
                    ambiguous_observation_count=0,
                    last_ambiguous_observed_at=None,
                    updated_at=succeeded_at,
                )
            )
