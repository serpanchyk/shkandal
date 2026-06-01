"""Ingestion worker configuration."""

from shkandal_common.config import BaseServiceConfig


class IngestionConfig(BaseServiceConfig):
    service_name: str = "worker-ingestion"
    poll_interval_seconds: int = 30
    postgres_database_url: str = (
        "postgresql://shkandal:shkandal_dev_password@postgres:5432/shkandal"
    )
