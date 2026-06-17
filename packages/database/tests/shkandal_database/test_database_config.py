"""Tests for database configuration."""

from shkandal_database.config import DatabaseConfig


def test_database_config_reads_postgres_database_url(monkeypatch) -> None:
    monkeypatch.setenv(
        "POSTGRES_DATABASE_URL",
        "postgresql://user:password@localhost:5432/shkandal",
    )

    config = DatabaseConfig()

    assert config.database_url == "postgresql://user:password@localhost:5432/shkandal"
    assert config.async_database_url == "postgresql+asyncpg://user:password@localhost:5432/shkandal"


def test_database_config_preserves_async_url(monkeypatch) -> None:
    monkeypatch.setenv(
        "POSTGRES_DATABASE_URL",
        "postgresql+asyncpg://user:password@localhost:5432/shkandal",
    )

    config = DatabaseConfig()

    assert config.async_database_url == "postgresql+asyncpg://user:password@localhost:5432/shkandal"
