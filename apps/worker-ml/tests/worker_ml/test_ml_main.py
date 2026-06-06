import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import worker_ml.main as entrypoint
from shkandal_database.jobs import ArticleJobStore
from worker_ml.classifier import ClassificationJobHandler
from worker_ml.config import MlConfig
from worker_ml.jobs import MlJobPlanner
from worker_ml.main import _run_cycle


@pytest.mark.asyncio
async def test_run_cycle_enqueues_and_processes_bounded_batch() -> None:
    planner = Mock(spec=MlJobPlanner)
    planner.enqueue_missing_classification_jobs = AsyncMock(
        return_value=SimpleNamespace(scanned_articles=10, ensured_jobs=4)
    )
    claimed_jobs = [
        SimpleNamespace(
            id=f"job-{index}",
            article_id=f"article-{index}",
            job_type="classify_article",
            attempt_count=1,
            max_attempts=3,
        )
        for index in range(3)
    ]
    job_store = Mock(spec=ArticleJobStore)
    job_store.claim_next_job = AsyncMock(side_effect=claimed_jobs)
    job_store.complete_job = AsyncMock()
    job_store.fail_job = AsyncMock()
    handler = Mock(spec=ClassificationJobHandler)
    handler.handle = AsyncMock()

    result = await _run_cycle(
        settings=MlConfig(
            service_name="ml-test",
            enqueue_batch_size=10,
            claim_batch_size=3,
        ),
        logger=Mock(),
        planner=planner,
        job_store=job_store,
        handler=handler,
    )

    assert result == {
        "scanned_articles": 10,
        "ensured_jobs": 4,
        "processed_jobs": 3,
        "failed_jobs": 0,
    }
    assert job_store.claim_next_job.await_count == 3
    assert handler.handle.await_count == 3
    assert job_store.complete_job.await_count == 3


def test_once_flag_dispatches_one_cycle(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []

    def run(coroutine: object) -> None:
        called.append(coroutine.cr_code.co_name)  # type: ignore[attr-defined]
        coroutine.close()  # type: ignore[attr-defined]

    monkeypatch.setattr(sys, "argv", ["worker-ml", "--once"])
    monkeypatch.setattr(asyncio, "run", run)

    entrypoint.main()

    assert called == ["run_once"]


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
