"""ML worker configuration."""

from datetime import timedelta

from shkandal_common.config import BaseServiceConfig


class MlConfig(BaseServiceConfig):
    service_name: str = "worker-ml"
    poll_interval_seconds: int = 30
    enqueue_batch_size: int = 500
    claim_batch_size: int = 50
    stale_job_timeout_seconds: int = 1800
    job_max_attempts: int = 3
    relevance_model_dir: str = "artifacts/models/relevance/tfidf_logistic_noise_assigned"
    relevance_threshold: float = 0.5
    embedding_model_dir: str = "artifacts/models/embeddings/multilingual_e5_small/model"
    embedding_vector_size: int = 384
    postgres_database_url: str = (
        "postgresql://shkandal:shkandal_dev_password@postgres:5432/shkandal"
    )
    qdrant_url: str = "http://qdrant:6333"
    llm_api_base: str = "http://llm-proxy:4000/v1"
    llm_api_key: str = "replace-me"
    llm_request_timeout_seconds: int = 300
    llm_article_card_model: str = "shkandal-article-card"
    llm_case_resolution_model: str = "shkandal-case-resolution"
    llm_entity_resolution_model: str = "shkandal-entity-resolution"
    llm_event_resolution_model: str = "shkandal-event-resolution"
    llm_repair_model: str = "shkandal-repair"

    @property
    def stale_job_timeout(self) -> timedelta:
        """Return the configured stale-job lease timeout."""

        return timedelta(seconds=self.stale_job_timeout_seconds)
