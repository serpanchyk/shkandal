"""ML worker configuration."""

from datetime import timedelta
from typing import Literal

from pydantic import Field
from shkandal_common.config import BaseServiceConfig


class MlConfig(BaseServiceConfig):
    service_name: str = "worker-ml"
    poll_interval_seconds: int = 30
    enqueue_batch_size: int = 500
    claim_batch_size: int = 50
    worker_concurrency: int = 4
    stale_job_timeout_seconds: int = 1800
    job_max_attempts: int = 3
    transient_retry_delay_min_seconds: int = Field(default=10, gt=0)
    relevance_model_dir: str = "artifacts/models/relevance/tfidf_logistic_noise_assigned"
    relevance_threshold: float = 0.5
    embedding_model_dir: str = "artifacts/models/embeddings/multilingual_e5_small/model"
    embedding_vector_size: int = 384
    case_resolution_candidate_limit: int = Field(default=12, gt=0)
    entity_resolution_candidate_limit: int = Field(default=8, gt=0)
    event_resolution_candidate_limit: int = Field(default=8, gt=0)
    article_card_text_max_chars: int = Field(default=20_000, gt=0)
    llm_max_output_tokens: int = Field(default=4_096, gt=0)
    postgres_database_url: str = (
        "postgresql://shkandal:shkandal_dev_password@postgres:5432/shkandal"
    )
    qdrant_url: str = "http://qdrant:6333"
    llm_api_base: str = "http://llm-proxy:4000/v1"
    llm_api_key: str = "replace-me"
    llm_request_timeout_seconds: int = 300
    llm_article_gate_model: str = "shkandal-article-gate"
    llm_article_card_model: str = "shkandal-article-card"
    llm_case_resolution_model: str = "shkandal-case-resolution"
    llm_entity_resolution_model: str = "shkandal-entity-resolution"
    llm_event_resolution_model: str = "shkandal-event-resolution"
    llm_refresh_case_model: str = "shkandal-refresh-case"
    llm_case_coherence_audit_model: str = "shkandal-case-coherence-audit"
    llm_case_public_interest_audit_model: str = "shkandal-case-public-interest-audit"
    llm_case_duplicate_audit_model: str = "shkandal-case-duplicate-audit"
    llm_repair_model: str = "shkandal-repair"
    llm_structured_output_mode: Literal["disabled", "tool_calling", "json_schema"] = "disabled"
    case_audit_interval_days: int = 30
    case_audit_enqueue_batch_size: int = 20
    case_audit_card_batch_size: int = Field(default=20, gt=0)
    case_audit_min_card_batch_size: int = Field(default=2, gt=0)
    case_audit_manual_default_limit: int = Field(default=5, gt=0)
    case_link_audit_card_limit: int = Field(default=20, gt=0)
    case_review_card_limit: int = Field(default=40, gt=0)
    refresh_case_card_limit: int = Field(default=40, gt=0)
    refresh_case_enqueue_batch_size: int = Field(default=20, gt=0)
    refresh_case_repair_priority: int = Field(default=100, gt=0)
    case_resolution_representative_title_limit: int = Field(default=8, gt=0)
    case_resolution_enqueue_batch_size: int = Field(default=5_000, gt=0)
    article_card_reprocess_job_upsert_batch_size: int = Field(default=1_000, gt=0)
    case_resolution_connectivity_example_limit: int = Field(default=20, gt=0)
    case_audit_automatic_enabled: bool = True

    @property
    def stale_job_timeout(self) -> timedelta:
        """Return the configured stale-job lease timeout."""

        return timedelta(seconds=self.stale_job_timeout_seconds)
