import pytest
from worker_ml.config import MlConfig
from worker_ml.main import run_once


@pytest.mark.asyncio
async def test_run_once_smoke() -> None:
    result = await run_once(MlConfig(service_name="ml-test"))

    assert result == {"service": "ml-test", "status": "ok"}


def test_stale_job_timeout_config() -> None:
    config = MlConfig(stale_job_timeout_seconds=60)

    assert config.stale_job_timeout.total_seconds() == 60


def test_classifier_config_defaults_to_existing_artifact() -> None:
    config = MlConfig()

    assert config.relevance_model_dir.endswith("tfidf_logistic_noise_assigned")
    assert config.relevance_threshold == 0.5


def test_embedding_config_defaults_to_e5_small_artifact() -> None:
    config = MlConfig()

    assert config.embedding_model_dir.endswith("multilingual_e5_small/model")
    assert config.embedding_vector_size == 384


def test_llm_config_defaults_to_litellm_proxy_aliases() -> None:
    fields = MlConfig.model_fields

    assert fields["llm_api_base"].default == "http://llm-proxy:4000/v1"
    assert fields["llm_article_card_model"].default == "shkandal-article-card"
    assert fields["llm_case_resolution_model"].default == "shkandal-case-resolution"
    assert fields["llm_entity_resolution_model"].default == "shkandal-entity-resolution"
    assert fields["llm_event_resolution_model"].default == "shkandal-event-resolution"
    assert fields["llm_repair_model"].default == "shkandal-repair"
