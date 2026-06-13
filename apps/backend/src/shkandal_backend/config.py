"""Backend service configuration."""

from pydantic import Field
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
    image_check_timeout_seconds: float = Field(default=2.0, gt=0, le=10)
    image_check_max_candidates: int = Field(default=5, ge=1, le=20)
    image_check_cache_ttl_seconds: float = Field(default=300, ge=0, le=3600)
