"""Ingestion worker configuration."""

from pydantic import Field
from shkandal_common.config import BaseServiceConfig


class IngestionConfig(BaseServiceConfig):
    service_name: str = "worker-ingestion"
    poll_interval_seconds: int = 30
    postgres_database_url: str = (
        "postgresql://shkandal:shkandal_dev_password@postgres:5432/shkandal"
    )
    request_timeout_seconds: float = 20.0
    request_concurrency: int = 5
    request_user_agent: str = Field(
        default=(
            "Shkandal ingestion worker "
            "(https://github.com/serpanchyk/shkandal; contact: admin@example.invalid)"
        ),
    )
    max_sitemap_urls_per_source: int = 500
    max_backfill_urls_per_source: int = 10_000

    async def service_status(self) -> dict[str, str]:
        return {"service": self.service_name, "status": "ok"}
