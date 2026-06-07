"""Persistence helpers for LLM run metadata."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from shkandal_database.models import LlmRun
from shkandal_database.session import async_session_scope
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from worker_ml.llm.contracts import LlmRunType


class LlmRunStore:
    """Create and update `llm_runs` records around model calls."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_run(
        self,
        *,
        run_type: LlmRunType,
        prompt_name: str,
        prompt_version: str,
        model_name: str,
        metadata: dict[str, Any] | None = None,
        started_at: datetime | None = None,
    ) -> UUID:
        """Persist a pending LLM run and return its id."""

        async with async_session_scope(self._session_factory) as session:
            run = LlmRun(
                run_type=run_type,
                prompt_name=prompt_name,
                prompt_version=prompt_version,
                model_name=model_name,
                status="pending",
                metadata_=metadata or {},
                started_at=started_at or datetime.now(UTC),
            )
            session.add(run)
            await session.flush()
            return run.id

    async def finish_run(
        self,
        *,
        run_id: UUID,
        status: str,
        raw_output: dict[str, Any] | None = None,
        repaired_output: dict[str, Any] | None = None,
        error_message: str | None = None,
        metadata: dict[str, Any] | None = None,
        finished_at: datetime | None = None,
    ) -> None:
        """Mark a pending LLM run as finished."""

        values: dict[str, Any] = {
            "status": status,
            "raw_output": raw_output,
            "repaired_output": repaired_output,
            "error_message": error_message,
            "finished_at": finished_at or datetime.now(UTC),
        }
        if metadata is not None:
            values["metadata_"] = metadata

        async with async_session_scope(self._session_factory) as session:
            await session.execute(update(LlmRun).where(LlmRun.id == run_id).values(**values))
