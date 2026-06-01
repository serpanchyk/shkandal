"""Tests for async session helpers."""

from shkandal_database.config import DatabaseConfig
from shkandal_database.session import create_async_engine_from_config, create_async_sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def test_create_async_sessionmaker_without_connecting() -> None:
    engine = create_async_engine_from_config(
        DatabaseConfig(
            database_url="postgresql://user:password@localhost:5432/shkandal",
        ),
    )

    session_factory = create_async_sessionmaker(engine)

    assert isinstance(session_factory, async_sessionmaker)
    assert session_factory.class_ is AsyncSession
    assert str(engine.url).startswith("postgresql+asyncpg://")
