"""PostgreSQL-backed shared LLM cooldown state."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from shkandal_database.models import LlmCooldown
from shkandal_database.session import async_session_scope

DEFAULT_LLM_COOLDOWN_SCOPE = "shared-provider"


class LlmCooldownStore:
    """Read and extend the shared pause applied to all LLM jobs."""

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

    async def extend(self, *, resume_at: datetime, reason: str) -> datetime:
        """Create or extend the cooldown without shortening an existing pause."""

        updated_at = datetime.now(UTC)
        statement = (
            insert(LlmCooldown)
            .values(
                scope=self._scope,
                resume_at=resume_at,
                reason=reason,
                updated_at=updated_at,
            )
            .on_conflict_do_update(
                index_elements=[LlmCooldown.scope],
                set_={
                    "resume_at": resume_at,
                    "reason": reason,
                    "updated_at": updated_at,
                },
                where=LlmCooldown.resume_at < resume_at,
            )
            .returning(LlmCooldown.resume_at)
        )
        async with async_session_scope(self._session_factory) as session:
            stored_resume_at = await session.scalar(statement)
            if stored_resume_at is not None:
                return stored_resume_at
            existing_resume_at = await session.scalar(
                select(LlmCooldown.resume_at).where(LlmCooldown.scope == self._scope)
            )
        if existing_resume_at is None:
            raise RuntimeError("LLM cooldown upsert did not persist a row")
        return existing_resume_at
