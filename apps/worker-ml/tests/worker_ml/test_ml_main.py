import asyncio
import sys
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import worker_ml.main as entrypoint
from shkandal_database.jobs import ArticleJobStore
from shkandal_database.llm_cooldowns import LlmCooldownDecision, LlmCooldownStore
from worker_ml.article_cards import ArticleCardJobHandler
from worker_ml.classifier import ClassificationJobHandler, RelevanceModel
from worker_ml.config import MlConfig
from worker_ml.jobs import EnqueueStats, MlJobPlanner
from worker_ml.llm.runner import LlmRateLimitError
from worker_ml.main import _run_cycle


@pytest.mark.asyncio
async def test_run_cycle_enqueues_and_processes_bounded_batch() -> None:
    planner = Mock(spec=MlJobPlanner)
    planner.enqueue_missing_classification_jobs = AsyncMock(
        return_value=EnqueueStats(
            scanned_articles=10,
            ensured_jobs=4,
            inserted_jobs=3,
            requeued_jobs=1,
            existing_jobs=6,
        )
    )
    claimed_jobs = [
        SimpleNamespace(
            id=f"job-{index}",
            article_id=f"article-{index}",
            job_type="create_article_card" if index == 1 else "classify_article",
            attempt_count=1,
            max_attempts=3,
        )
        for index in range(3)
    ]
    job_store = Mock(spec=ArticleJobStore)
    job_store.claim_next_job = AsyncMock(side_effect=claimed_jobs)
    job_store.complete_job = AsyncMock()
    job_store.fail_job = AsyncMock()
    cooldown_store = Mock(spec=LlmCooldownStore)
    cooldown_store.active_resume_at = AsyncMock(return_value=None)
    classification_handler = Mock(spec=ClassificationJobHandler)
    classification_handler.handle = AsyncMock()
    article_card_handler = Mock(spec=ArticleCardJobHandler)
    article_card_handler.handle = AsyncMock()

    result = await _run_cycle(
        settings=MlConfig(
            service_name="ml-test",
            enqueue_batch_size=10,
            claim_batch_size=3,
        ),
        logger=Mock(),
        planner=planner,
        job_store=job_store,
        cooldown_store=cooldown_store,
        handlers={
            "classify_article": classification_handler,
            "create_article_card": article_card_handler,
        },
    )

    assert result == {
        "scanned_articles": 10,
        "ensured_jobs": 4,
        "processed_jobs": 3,
        "failed_jobs": 0,
    }
    assert job_store.claim_next_job.await_count == 3
    assert classification_handler.handle.await_count == 2
    article_card_handler.handle.assert_awaited_once_with(claimed_jobs[1])
    assert job_store.claim_next_job.await_args.kwargs["job_types"] == (
        "classify_article",
        "create_article_card",
        "resolve_article_cases",
        "resolve_article_entities",
        "resolve_article_events",
        "update_case_copy",
    )
    assert job_store.complete_job.await_count == 3


@pytest.mark.asyncio
async def test_run_cycle_defers_rate_limited_job_and_ends_pass() -> None:
    planner = Mock(spec=MlJobPlanner)
    planner.enqueue_missing_classification_jobs = AsyncMock(
        return_value=EnqueueStats(
            scanned_articles=0,
            ensured_jobs=0,
            inserted_jobs=0,
            requeued_jobs=0,
            existing_jobs=0,
        )
    )
    card_job = SimpleNamespace(
        id="card-job",
        article_id="card-article",
        job_type="create_article_card",
        attempt_count=1,
        max_attempts=3,
    )
    classifier_job = SimpleNamespace(
        id="classifier-job",
        article_id="classifier-article",
        job_type="classify_article",
        attempt_count=1,
        max_attempts=3,
    )
    job_store = Mock(spec=ArticleJobStore)
    job_store.claim_next_job = AsyncMock(side_effect=[card_job, classifier_job])
    job_store.complete_job = AsyncMock()
    job_store.fail_job = AsyncMock()
    job_store.defer_job = AsyncMock()
    resume_at = datetime(2026, 6, 8, 16, 0, tzinfo=UTC)
    cooldown_store = Mock(spec=LlmCooldownStore)
    cooldown_store.active_resume_at = AsyncMock(return_value=None)
    cooldown_store.record_rate_limit = AsyncMock(
        return_value=LlmCooldownDecision(
            resume_at=resume_at,
            kind="provider_long",
            ambiguous_observation_count=0,
        )
    )
    classification_handler = Mock(spec=ClassificationJobHandler)
    classification_handler.handle = AsyncMock()
    article_card_handler = Mock(spec=ArticleCardJobHandler)
    article_card_handler.handle = AsyncMock(
        side_effect=LlmRateLimitError("quota exhausted", retry_after_seconds=3600)
    )

    result = await _run_cycle(
        settings=MlConfig(claim_batch_size=2),
        logger=Mock(),
        planner=planner,
        job_store=job_store,
        cooldown_store=cooldown_store,
        handlers={
            "classify_article": classification_handler,
            "create_article_card": article_card_handler,
        },
    )

    assert result["processed_jobs"] == 0
    assert result["failed_jobs"] == 0
    job_store.defer_job.assert_awaited_once()
    job_store.claim_next_job.assert_awaited_once()
    classification_handler.handle.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_cycle_exits_before_enqueue_or_claim_during_active_cooldown() -> None:
    planner = Mock(spec=MlJobPlanner)
    planner.enqueue_missing_classification_jobs = AsyncMock(
        return_value=EnqueueStats(
            scanned_articles=0,
            ensured_jobs=0,
            inserted_jobs=0,
            requeued_jobs=0,
            existing_jobs=0,
        )
    )
    job_store = Mock(spec=ArticleJobStore)
    job_store.claim_next_job = AsyncMock(return_value=None)
    cooldown_store = Mock(spec=LlmCooldownStore)
    cooldown_store.active_resume_at = AsyncMock(
        return_value=datetime(2026, 6, 8, 16, 0, tzinfo=UTC)
    )

    await _run_cycle(
        settings=MlConfig(claim_batch_size=1),
        logger=Mock(),
        planner=planner,
        job_store=job_store,
        cooldown_store=cooldown_store,
        handlers={},
    )

    planner.enqueue_missing_classification_jobs.assert_not_awaited()
    job_store.claim_next_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_cycle_continues_after_ordinary_api_failure() -> None:
    planner = Mock(spec=MlJobPlanner)
    planner.enqueue_missing_classification_jobs = AsyncMock(
        return_value=EnqueueStats(0, 0, 0, 0, 0)
    )
    failed_job = SimpleNamespace(
        id="failed-job",
        article_id="failed-article",
        job_type="create_article_card",
        attempt_count=1,
        max_attempts=3,
    )
    next_job = SimpleNamespace(
        id="next-job",
        article_id="next-article",
        job_type="classify_article",
        attempt_count=1,
        max_attempts=3,
    )
    job_store = Mock(spec=ArticleJobStore)
    job_store.claim_next_job = AsyncMock(side_effect=[failed_job, next_job])
    job_store.complete_job = AsyncMock()
    job_store.fail_job = AsyncMock()
    cooldown_store = Mock(spec=LlmCooldownStore)
    cooldown_store.active_resume_at = AsyncMock(return_value=None)
    cooldown_store.clear_expired_ambiguous_observation = AsyncMock()
    card_handler = Mock(spec=ArticleCardJobHandler)
    card_handler.handle = AsyncMock(side_effect=RuntimeError("provider error"))
    classifier_handler = Mock(spec=ClassificationJobHandler)
    classifier_handler.handle = AsyncMock()

    result = await _run_cycle(
        settings=MlConfig(claim_batch_size=2),
        logger=Mock(),
        planner=planner,
        job_store=job_store,
        cooldown_store=cooldown_store,
        handlers={
            "classify_article": classifier_handler,
            "create_article_card": card_handler,
        },
    )

    assert result["failed_jobs"] == 1
    assert result["processed_jobs"] == 1
    job_store.fail_job.assert_awaited_once()
    classifier_handler.handle.assert_awaited_once_with(next_job)


@pytest.mark.asyncio
async def test_run_once_active_cooldown_exits_before_model_loading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = Mock()
    engine.dispose = AsyncMock()
    cooldown_store = Mock(spec=LlmCooldownStore)
    cooldown_store.active_resume_at = AsyncMock(
        return_value=datetime(2026, 6, 10, 16, 0, tzinfo=UTC)
    )
    load = Mock()
    monkeypatch.setattr(entrypoint, "create_async_engine_from_config", Mock(return_value=engine))
    monkeypatch.setattr(entrypoint, "create_async_sessionmaker", Mock())
    monkeypatch.setattr(entrypoint, "LlmCooldownStore", Mock(return_value=cooldown_store))
    monkeypatch.setattr(RelevanceModel, "load", load)

    result = await entrypoint.run_once(MlConfig())

    assert result["processed_jobs"] == 0
    load.assert_not_called()


def test_no_args_dispatches_one_cycle(monkeypatch: pytest.MonkeyPatch) -> None:
    run_once = AsyncMock()
    monkeypatch.setattr(sys, "argv", ["worker-ml"])
    monkeypatch.setattr(entrypoint, "run_once", run_once)

    entrypoint.main()

    run_once.assert_awaited_once_with()


def test_loop_flag_dispatches_worker_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    run_worker = AsyncMock()
    monkeypatch.setattr(sys, "argv", ["worker-ml", "--loop"])
    monkeypatch.setattr(entrypoint, "run_worker", run_worker)

    entrypoint.main()

    run_worker.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_worker_loop_sleeps_when_cycle_is_idle(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = Mock()
    engine.dispose = AsyncMock()
    run_cycle = AsyncMock(
        side_effect=[
            {"scanned_articles": 1, "ensured_jobs": 0, "processed_jobs": 0, "failed_jobs": 0},
            asyncio.CancelledError,
        ]
    )
    sleep = AsyncMock()
    monkeypatch.setattr(RelevanceModel, "load", Mock())
    monkeypatch.setattr(entrypoint, "create_async_engine_from_config", Mock(return_value=engine))
    monkeypatch.setattr(entrypoint, "create_async_sessionmaker", Mock())
    cooldown_store = Mock(spec=LlmCooldownStore)
    cooldown_store.active_resume_at = AsyncMock(return_value=None)
    monkeypatch.setattr(entrypoint, "LlmCooldownStore", Mock(return_value=cooldown_store))
    monkeypatch.setattr(entrypoint, "_run_cycle", run_cycle)
    monkeypatch.setattr(asyncio, "sleep", sleep)

    with pytest.raises(asyncio.CancelledError):
        await entrypoint.run_worker(MlConfig(poll_interval_seconds=17))

    sleep.assert_awaited_once_with(17)


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
    assert fields["llm_case_copy_update_model"].default == "shkandal-case-copy-update"
    assert fields["llm_repair_model"].default == "shkandal-repair"
