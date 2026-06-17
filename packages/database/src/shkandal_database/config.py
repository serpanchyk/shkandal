"""Database configuration."""

from urllib.parse import quote

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
            return _normalize_postgres_url_userinfo(self.database_url)
        if self.database_url.startswith("postgresql://"):
            url = self.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
            return _normalize_postgres_url_userinfo(url)
        return self.database_url


def _normalize_postgres_url_userinfo(url: str) -> str:
    """Percent-encode unescaped PostgreSQL URL userinfo delimiters."""

    scheme_separator = "://"
    if scheme_separator not in url:
        return url
    scheme, rest = url.split(scheme_separator, 1)
    if "@" not in rest:
        return url

    userinfo, host_and_path = rest.rsplit("@", 1)
    if ":" in userinfo:
        username, password = userinfo.split(":", 1)
        normalized_userinfo = f"{quote(username, safe='%')}:{quote(password, safe='%')}"
    else:
        normalized_userinfo = quote(userinfo, safe="%")
    return f"{scheme}{scheme_separator}{normalized_userinfo}@{host_and_path}"
