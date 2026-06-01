"""ML worker configuration."""

from shkandal_common.config import BaseServiceConfig


class MlConfig(BaseServiceConfig):
    service_name: str = "worker-ml"
    poll_interval_seconds: int = 30
    postgres_database_url: str = (
        "postgresql://shkandal:shkandal_dev_password@postgres:5432/shkandal"
    )
    qdrant_url: str = "http://qdrant:6333"
    llm_api_base: str = "https://llm.example.invalid/v1"
    llm_api_key: str = "replace-me"
