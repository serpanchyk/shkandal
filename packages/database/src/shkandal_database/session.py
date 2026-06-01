"""Async SQLAlchemy engine and session helpers."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from shkandal_database.config import DatabaseConfig


def create_async_engine_from_config(config: DatabaseConfig | None = None) -> AsyncEngine:
    """Create an async SQLAlchemy engine from database settings."""

    settings = config or DatabaseConfig()
    return create_async_engine(settings.async_database_url, pool_pre_ping=True)


def create_async_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create the shared async session factory."""

    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def async_session_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Open a transaction-scoped async session."""

    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
