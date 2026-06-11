"""Backend service configuration."""

from shkandal_common.config import BaseServiceConfig


class BackendConfig(BaseServiceConfig):
    service_name: str = "backend"
    host: str = "0.0.0.0"
    port: int = 8000
    postgres_database_url: str = (
        "postgresql://shkandal:shkandal_dev_password@postgres:5432/shkandal"
    )
    qdrant_url: str = "http://qdrant:6333"
    public_frontend_origin: str = "http://localhost:3000"
