"""Database configuration."""

from pydantic import Field
from shkandal_common.config import BaseServiceConfig


class DatabaseConfig(BaseServiceConfig):
    """Settings used by the shared database package."""

    database_url: str = Field(
        default="postgresql+asyncpg://shkandal:shkandal_dev_password@postgres:5432/shkandal",
        validation_alias="POSTGRES_DATABASE_URL",
    )

    @property
    def async_database_url(self) -> str:
        """Return a SQLAlchemy async URL for PostgreSQL."""

        if self.database_url.startswith("postgresql+asyncpg://"):
            return self.database_url
        if self.database_url.startswith("postgresql://"):
            return self.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return self.database_url
