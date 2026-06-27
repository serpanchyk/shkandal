import asyncio
import sys
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
import worker_ml.main as cli_entrypoint
import worker_ml.runtime.application as entrypoint
import worker_ml.runtime.execution as execution
from shkandal_database.jobs import ArticleJobStore, JobQueueSummary
from shkandal_database.llm_cooldowns import LlmCooldownDecision, LlmCooldownStore
from shkandal_vector_store import VectorStoreUnavailableError
from worker_ml.articles.cards import ArticleCardJobHandler
from worker_ml.articles.relevance import ClassificationJobHandler, RelevanceModel
from worker_ml.config import MlConfig
from worker_ml.llm.runner import LlmDependencyUnavailableError, LlmRateLimitError
from worker_ml.retrieval.embeddings import E5Embedder
from worker_ml.runtime.execution import drain_backfill, run_cycle
from worker_ml.runtime.planning import EnqueueStats, MlJobPlanner


@pytest.mark.asyncio
async def testrun_cycle_enqueues_and_processes_bounded_batch() -> None:
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
    planner.enqueue_missing_article_card_jobs = AsyncMock(return_value=EnqueueStats(0, 0, 0, 0, 0))
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

    result = await run_cycle(
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

    assert result["scanned_articles"] == 10
    assert result["ensured_jobs"] == 4
    assert result["processed_jobs"] == 3
    assert result["failed_jobs"] == 0
    assert result["duration_seconds"] >= 0
    assert job_store.claim_next_job.await_count == 3
    assert classification_handler.handle.await_count == 2
    article_card_handler.handle.assert_awaited_once_with(claimed_jobs[1])
    assert all(
        len(call.kwargs["job_types"]) == 1 for call in job_store.claim_next_job.await_args_list
    )
    assert job_store.complete_job.await_count == 3


@pytest.mark.asyncio
async def testrun_cycle_discovers_and_claims_only_selected_job_types() -> None:
    planner = Mock(spec=MlJobPlanner)
    planner.enqueue_missing_article_card_jobs = AsyncMock(
        return_value=EnqueueStats(
            scanned_articles=2,
            ensured_jobs=1,
            inserted_jobs=1,
        )
    )
    card_job = SimpleNamespace(
        id="card-job",
        article_id="article-id",
        job_type="create_article_card",
        attempt_count=1,
        max_attempts=3,
    )

    job_store = Mock(spec=ArticleJobStore)
    job_store.claim_next_job = AsyncMock(side_effect=[card_job, None])
    job_store.complete_job = AsyncMock()
    job_store.fail_job = AsyncMock()
    cooldown_store = Mock(spec=LlmCooldownStore)
    cooldown_store.active_resume_at = AsyncMock(return_value=None)
    handler = Mock(spec=ArticleCardJobHandler)
    handler.handle = AsyncMock()

    result = await run_cycle(
        settings=MlConfig(claim_batch_size=2, worker_concurrency=1),
        logger=Mock(),
        planner=planner,
        job_store=job_store,
        cooldown_store=cooldown_store,
        handlers={"create_article_card": handler},
        job_types=("create_article_card",),
    )

    assert result["scanned_articles"] == 2
    assert result["ensured_jobs"] == 1
    planner.enqueue_missing_classification_jobs.assert_not_awaited()
    planner.enqueue_due_case_audit_jobs.assert_not_awaited()
    planner.enqueue_missing_article_card_jobs.assert_awaited_once()
    assert all(
        call.kwargs["job_types"] == ("create_article_card",)
        for call in job_store.claim_next_job.await_args_list
    )
    handler.handle.assert_awaited_once_with(card_job)


@pytest.mark.asyncio
async def testrun_cycle_defers_rate_limited_job_and_ends_pass() -> None:
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

    result = await run_cycle(
        settings=MlConfig(claim_batch_size=2, worker_concurrency=1),
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
async def test_run_cycle_defers_qdrant_unavailable_without_consuming_failure() -> None:
    planner = Mock(spec=MlJobPlanner)
    planner.enqueue_missing_classification_jobs = AsyncMock(
        return_value=EnqueueStats(0, 0, 0, 0, 0)
    )
    planner.enqueue_missing_article_card_jobs = AsyncMock(return_value=EnqueueStats(0, 0, 0, 0, 0))
    job = SimpleNamespace(
        id="case-job",
        article_id="case-article",
        job_type="resolve_article_cases",
        attempt_count=1,
        max_attempts=3,
    )
    job_store = Mock(spec=ArticleJobStore)
    job_store.claim_next_job = AsyncMock(return_value=job)
    job_store.complete_job = AsyncMock()
    job_store.fail_job = AsyncMock()
    job_store.defer_job = AsyncMock()
    cooldown_store = Mock(spec=LlmCooldownStore)
    cooldown_store.active_resume_at = AsyncMock(return_value=None)
    handler = Mock()
    handler.handle = AsyncMock(
        side_effect=VectorStoreUnavailableError(
            "Qdrant search failed: collection=case_cards, limit=12"
        )
    )

    result = await run_cycle(
        settings=MlConfig(claim_batch_size=2, worker_concurrency=1, poll_interval_seconds=30),
        logger=Mock(),
        planner=planner,
        job_store=job_store,
        cooldown_store=cooldown_store,
        handlers={"resolve_article_cases": handler},
    )

    assert result["processed_jobs"] == 0
    assert result["failed_jobs"] == 0
    job_store.defer_job.assert_awaited_once()
    job_store.fail_job.assert_not_awaited()
    job_store.complete_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_cycle_defers_litellm_unavailable_without_consuming_failure() -> None:
    planner = Mock(spec=MlJobPlanner)
    planner.enqueue_missing_classification_jobs = AsyncMock(
        return_value=EnqueueStats(0, 0, 0, 0, 0)
    )
    planner.enqueue_missing_article_card_jobs = AsyncMock(return_value=EnqueueStats(0, 0, 0, 0, 0))
    job = SimpleNamespace(
        id="card-job",
        article_id="card-article",
        job_type="create_article_card",
        attempt_count=1,
        max_attempts=3,
    )
    job_store = Mock(spec=ArticleJobStore)
    job_store.claim_next_job = AsyncMock(return_value=job)
    job_store.complete_job = AsyncMock()
    job_store.fail_job = AsyncMock()
    job_store.defer_job = AsyncMock()
    cooldown_store = Mock(spec=LlmCooldownStore)
    cooldown_store.active_resume_at = AsyncMock(return_value=None)
    handler = Mock()
    handler.handle = AsyncMock(
        side_effect=LlmDependencyUnavailableError("LiteLLM proxy unavailable")
    )

    result = await run_cycle(
        settings=MlConfig(claim_batch_size=2, worker_concurrency=1, poll_interval_seconds=30),
        logger=Mock(),
        planner=planner,
        job_store=job_store,
        cooldown_store=cooldown_store,
        handlers={"create_article_card": handler},
    )

    assert result["processed_jobs"] == 0
    assert result["failed_jobs"] == 0
    job_store.defer_job.assert_awaited_once()
    assert job_store.defer_job.await_args.kwargs["reason"] == "LiteLLM proxy unavailable"
    job_store.fail_job.assert_not_awaited()
    job_store.complete_job.assert_not_awaited()


@pytest.mark.asyncio
async def testrun_cycle_executes_at_most_configured_concurrency() -> None:
    planner = Mock(spec=MlJobPlanner)
    planner.enqueue_missing_classification_jobs = AsyncMock(
        return_value=EnqueueStats(0, 0, 0, 0, 0)
    )
    jobs = [
        SimpleNamespace(
            id=f"job-{index}",
            article_id=f"article-{index}",
            job_type="create_article_card",
            attempt_count=1,
            max_attempts=3,
        )
        for index in range(8)
    ]
    active = 0
    max_active = 0

    async def claim_next_job(**kwargs: Any) -> object | None:
        if kwargs["job_types"] != ("create_article_card",) or not jobs:
            return None
        return jobs.pop()

    async def handle(_job: object) -> None:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1

    job_store = Mock(spec=ArticleJobStore)
    job_store.claim_next_job = AsyncMock(side_effect=claim_next_job)
    job_store.complete_job = AsyncMock()
    job_store.fail_job = AsyncMock()
    cooldown_store = Mock(spec=LlmCooldownStore)
    cooldown_store.active_resume_at = AsyncMock(return_value=None)
    handler = Mock()
    handler.handle = AsyncMock(side_effect=handle)

    result = await run_cycle(
        settings=MlConfig(claim_batch_size=8, worker_concurrency=4),
        logger=Mock(),
        planner=planner,
        job_store=job_store,
        cooldown_store=cooldown_store,
        handlers={"create_article_card": handler},
    )

    assert result["processed_jobs"] == 8
    assert max_active == 4


@pytest.mark.asyncio
async def testrun_cycle_claims_downstream_work_while_cards_remain() -> None:
    planner = Mock(spec=MlJobPlanner)
    planner.enqueue_missing_classification_jobs = AsyncMock(
        return_value=EnqueueStats(0, 0, 0, 0, 0)
    )
    card_jobs = [
        SimpleNamespace(
            id=f"card-{index}",
            article_id=f"card-article-{index}",
            job_type="create_article_card",
            attempt_count=1,
            max_attempts=3,
        )
        for index in range(10)
    ]
    case_job: SimpleNamespace | None = SimpleNamespace(
        id="case-job",
        article_id="case-article",
        job_type="resolve_article_cases",
        attempt_count=1,
        max_attempts=3,
    )

    async def claim_next_job(**kwargs: Any) -> object | None:
        job_type = kwargs["job_types"][0]
        if job_type == "create_article_card" and card_jobs:
            return card_jobs.pop()
        if job_type == "resolve_article_cases":
            nonlocal case_job
            claimed, case_job = case_job, None
            return claimed
        return None

    job_store = Mock(spec=ArticleJobStore)
    job_store.claim_next_job = AsyncMock(side_effect=claim_next_job)
    job_store.complete_job = AsyncMock()
    job_store.fail_job = AsyncMock()
    cooldown_store = Mock(spec=LlmCooldownStore)
    cooldown_store.active_resume_at = AsyncMock(return_value=None)
    card_handler = Mock()
    card_handler.handle = AsyncMock()
    case_handler = Mock()
    case_handler.handle = AsyncMock()

    await run_cycle(
        settings=MlConfig(claim_batch_size=3, worker_concurrency=1),
        logger=Mock(),
        planner=planner,
        job_store=job_store,
        cooldown_store=cooldown_store,
        handlers={
            "create_article_card": card_handler,
            "resolve_article_cases": case_handler,
        },
    )

    case_handler.handle.assert_awaited_once()
    assert card_jobs


@pytest.mark.asyncio
async def testrun_cycle_claims_jobs_in_pipeline_priority_order() -> None:
    planner = Mock(spec=MlJobPlanner)
    planner.enqueue_missing_classification_jobs = AsyncMock(
        return_value=EnqueueStats(0, 0, 0, 0, 0)
    )
    jobs_by_type = {
        "create_article_card": [
            SimpleNamespace(
                id="card-job",
                article_id="article-id",
                job_type="create_article_card",
                attempt_count=1,
                max_attempts=3,
            )
        ],
        "update_case_copy": [
            SimpleNamespace(
                id="copy-job",
                article_id=None,
                case_id="case-id",
                job_type="update_case_copy",
                attempt_count=1,
                max_attempts=3,
                requested_revision=1,
            )
        ],
        "resolve_article_cases": [
            SimpleNamespace(
                id="case-job",
                article_id="article-id",
                job_type="resolve_article_cases",
                attempt_count=1,
                max_attempts=3,
            )
        ],
        "resolve_article_entities": [
            SimpleNamespace(
                id="entity-job",
                article_id="article-id",
                job_type="resolve_article_entities",
                attempt_count=1,
                max_attempts=3,
            )
        ],
        "resolve_article_events": [
            SimpleNamespace(
                id="event-job",
                article_id="article-id",
                job_type="resolve_article_events",
                attempt_count=1,
                max_attempts=3,
            )
        ],
    }

    async def claim_next_job(**kwargs: Any) -> object | None:
        jobs = jobs_by_type.get(kwargs["job_types"][0], [])
        return jobs.pop() if jobs else None

    job_store = Mock(spec=ArticleJobStore)
    job_store.claim_next_job = AsyncMock(side_effect=claim_next_job)
    job_store.complete_job = AsyncMock()
    job_store.fail_job = AsyncMock()
    cooldown_store = Mock(spec=LlmCooldownStore)
    cooldown_store.active_resume_at = AsyncMock(return_value=None)
    handled_job_types: list[str] = []

    async def handle(job: Any) -> None:
        handled_job_types.append(job.job_type)

    handlers = {}
    for job_type in jobs_by_type:
        handler = Mock()
        handler.handle = AsyncMock(side_effect=handle)
        handlers[job_type] = handler

    await run_cycle(
        settings=MlConfig(claim_batch_size=5, worker_concurrency=1),
        logger=Mock(),
        planner=planner,
        job_store=job_store,
        cooldown_store=cooldown_store,
        handlers=handlers,
    )

    assert handled_job_types == [
        "create_article_card",
        "update_case_copy",
        "resolve_article_cases",
        "resolve_article_entities",
        "resolve_article_events",
    ]


@pytest.mark.asyncio
async def testrun_cycle_serializes_case_namespace_jobs() -> None:
    planner = Mock(spec=MlJobPlanner)
    planner.enqueue_missing_classification_jobs = AsyncMock(
        return_value=EnqueueStats(0, 0, 0, 0, 0)
    )
    jobs_by_type = {
        "resolve_article_cases": [
            SimpleNamespace(
                id="case-job",
                article_id="case-article",
                job_type="resolve_article_cases",
                attempt_count=1,
                max_attempts=3,
            )
        ],
        "update_case_copy": [
            SimpleNamespace(
                id="copy-job",
                article_id=None,
                case_id="case-id",
                job_type="update_case_copy",
                attempt_count=1,
                max_attempts=3,
                requested_revision=1,
            )
        ],
    }
    active = 0
    max_active = 0

    async def claim_next_job(**kwargs: Any) -> object | None:
        jobs = jobs_by_type.get(kwargs["job_types"][0], [])
        return jobs.pop() if jobs else None

    async def handle(_job: object) -> None:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1

    job_store = Mock(spec=ArticleJobStore)
    job_store.claim_next_job = AsyncMock(side_effect=claim_next_job)
    job_store.complete_job = AsyncMock()
    job_store.fail_job = AsyncMock()
    cooldown_store = Mock(spec=LlmCooldownStore)
    cooldown_store.active_resume_at = AsyncMock(return_value=None)
    case_handler = Mock()
    case_handler.handle = AsyncMock(side_effect=handle)
    copy_handler = Mock()
    copy_handler.handle = AsyncMock(side_effect=handle)

    await run_cycle(
        settings=MlConfig(claim_batch_size=2, worker_concurrency=4),
        logger=Mock(),
        planner=planner,
        job_store=job_store,
        cooldown_store=cooldown_store,
        handlers={
            "resolve_article_cases": case_handler,
            "update_case_copy": copy_handler,
        },
    )

    assert max_active == 1


@pytest.mark.asyncio
async def testrun_cycle_exits_before_enqueue_or_claim_during_active_cooldown() -> None:
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

    await run_cycle(
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
async def testrun_cycle_continues_after_ordinary_api_failure() -> None:
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

    result = await run_cycle(
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
    monkeypatch.setattr(cli_entrypoint, "run_once", run_once)

    cli_entrypoint.main()

    run_once.assert_awaited_once_with(
        job_types=(
            "create_article_card",
            "update_case_copy",
            "audit_case_coherence",
            "audit_case_public_interest",
            "audit_case_duplicates",
            "resolve_article_cases",
            "resolve_article_entities",
            "resolve_article_events",
            "classify_article",
        ),
    )


def test_loop_flag_dispatches_worker_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    run_worker = AsyncMock()
    monkeypatch.setattr(sys, "argv", ["worker-ml", "--loop"])
    monkeypatch.setattr(cli_entrypoint, "run_worker", run_worker)

    cli_entrypoint.main()

    run_worker.assert_awaited_once_with(
        job_types=(
            "create_article_card",
            "update_case_copy",
            "audit_case_coherence",
            "audit_case_public_interest",
            "audit_case_duplicates",
            "resolve_article_cases",
            "resolve_article_entities",
            "resolve_article_events",
            "classify_article",
        ),
    )


def test_job_type_flags_filter_and_order_worker_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    run_once = AsyncMock()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "worker-ml",
            "--job-type",
            "classify_article",
            "--job-type",
            "create_article_card",
            "--job-type",
            "create_article_card",
        ],
    )
    monkeypatch.setattr(cli_entrypoint, "run_once", run_once)

    cli_entrypoint.main()

    run_once.assert_awaited_once_with(
        job_types=("create_article_card", "classify_article"),
    )


def test_job_type_flag_rejects_unsupported_type(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["worker-ml", "--job-type", "unknown"])

    with pytest.raises(SystemExit, match="2"):
        cli_entrypoint.main()


def test_backfill_flag_dispatches_successful_backfill(monkeypatch: pytest.MonkeyPatch) -> None:
    run_backfill = AsyncMock(
        return_value=JobQueueSummary(
            queued_jobs=0,
            running_jobs=0,
            blocked_jobs=0,
            failed_jobs=0,
            next_run_after=None,
        )
    )
    monkeypatch.setattr(sys, "argv", ["worker-ml", "--backfill"])
    monkeypatch.setattr(cli_entrypoint, "run_backfill", run_backfill)

    cli_entrypoint.main()

    run_backfill.assert_awaited_once_with(
        job_types=(
            "create_article_card",
            "update_case_copy",
            "audit_case_coherence",
            "audit_case_public_interest",
            "audit_case_duplicates",
            "resolve_article_cases",
            "resolve_article_entities",
            "resolve_article_events",
            "classify_article",
        ),
    )


def test_backfill_flag_exits_nonzero_for_exhausted_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_backfill = AsyncMock(
        return_value=JobQueueSummary(
            queued_jobs=0,
            running_jobs=0,
            blocked_jobs=0,
            failed_jobs=2,
            next_run_after=None,
        )
    )
    monkeypatch.setattr(sys, "argv", ["worker-ml", "--backfill"])
    monkeypatch.setattr(cli_entrypoint, "run_backfill", run_backfill)

    with pytest.raises(SystemExit, match="1"):
        cli_entrypoint.main()


def test_backfill_flag_exits_nonzero_for_blocked_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    run_backfill = AsyncMock(
        return_value=JobQueueSummary(
            queued_jobs=0,
            running_jobs=1,
            blocked_jobs=1,
            failed_jobs=0,
            next_run_after=None,
            blocked_running_jobs=1,
        )
    )
    monkeypatch.setattr(sys, "argv", ["worker-ml", "--backfill"])
    monkeypatch.setattr(cli_entrypoint, "run_backfill", run_backfill)

    with pytest.raises(SystemExit, match="1"):
        cli_entrypoint.main()


def test_worker_modes_are_mutually_exclusive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["worker-ml", "--loop", "--backfill"])

    with pytest.raises(SystemExit, match="2"):
        cli_entrypoint.main()


@pytest.mark.asyncio
async def test_run_backfill_builds_resources_once_and_disposes_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = Mock()
    engine.dispose = AsyncMock()
    session_factory = Mock()
    model = Mock()
    job_store = Mock(spec=ArticleJobStore)
    planner = Mock(spec=MlJobPlanner)
    cooldown_store = Mock(spec=LlmCooldownStore)
    handlers = {"classify_article": Mock()}
    summary = JobQueueSummary(
        queued_jobs=0,
        running_jobs=0,
        blocked_jobs=0,
        failed_jobs=0,
        next_run_after=None,
    )
    drain_backfill = AsyncMock(return_value=summary)
    monkeypatch.setattr(entrypoint, "create_async_engine_from_config", Mock(return_value=engine))
    monkeypatch.setattr(entrypoint, "create_async_sessionmaker", Mock(return_value=session_factory))
    monkeypatch.setattr(entrypoint, "LlmCooldownStore", Mock(return_value=cooldown_store))
    monkeypatch.setattr(RelevanceModel, "load", Mock(return_value=model))
    monkeypatch.setattr(entrypoint, "ArticleJobStore", Mock(return_value=job_store))
    monkeypatch.setattr(entrypoint, "MlJobPlanner", Mock(return_value=planner))
    monkeypatch.setattr(entrypoint, "create_handlers", Mock(return_value=handlers))
    monkeypatch.setattr(entrypoint, "drain_backfill", drain_backfill)
    monkeypatch.setattr(entrypoint, "cleanup_stale_llm_runs", AsyncMock())

    result = await entrypoint.run_backfill(MlConfig(service_name="backfill-test"))

    assert result == summary
    assert drain_backfill.await_args is not None
    assert drain_backfill.await_args.kwargs["handlers"] == handlers
    engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_backfill_drains_new_jobs_before_exiting(monkeypatch: pytest.MonkeyPatch) -> None:
    run_cycle = AsyncMock(
        side_effect=[
            {"scanned_articles": 1, "ensured_jobs": 1, "processed_jobs": 1, "failed_jobs": 0},
            {"scanned_articles": 0, "ensured_jobs": 0, "processed_jobs": 1, "failed_jobs": 0},
        ]
    )
    monkeypatch.setattr(execution, "run_cycle", run_cycle)
    job_store = Mock(spec=ArticleJobStore)
    job_store.summarize_jobs = AsyncMock(
        side_effect=[
            JobQueueSummary(
                queued_jobs=1,
                running_jobs=0,
                blocked_jobs=0,
                failed_jobs=0,
                next_run_after=None,
            ),
            JobQueueSummary(
                queued_jobs=0,
                running_jobs=0,
                blocked_jobs=0,
                failed_jobs=0,
                next_run_after=None,
            ),
        ]
    )
    cooldown_store = Mock(spec=LlmCooldownStore)
    cooldown_store.active_resume_at = AsyncMock(return_value=None)

    summary = await drain_backfill(
        settings=MlConfig(),
        logger=Mock(),
        planner=Mock(spec=MlJobPlanner),
        job_store=job_store,
        cooldown_store=cooldown_store,
        handlers={},
    )

    assert summary.failed_jobs == 0
    assert run_cycle.await_count == 2
    assert run_cycle.await_args is not None
    assert run_cycle.await_args.kwargs["requeue_failed"] is False


@pytest.mark.asyncio
async def test_filtered_backfill_summarizes_only_selected_job_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_cycle = AsyncMock(
        return_value={
            "scanned_articles": 0,
            "ensured_jobs": 0,
            "processed_jobs": 0,
            "failed_jobs": 0,
        }
    )
    monkeypatch.setattr(execution, "run_cycle", run_cycle)
    job_store = Mock(spec=ArticleJobStore)
    job_store.summarize_jobs = AsyncMock(
        return_value=JobQueueSummary(
            queued_jobs=0,
            running_jobs=0,
            blocked_jobs=0,
            failed_jobs=0,
            next_run_after=None,
        )
    )
    cooldown_store = Mock(spec=LlmCooldownStore)
    cooldown_store.active_resume_at = AsyncMock(return_value=None)

    await drain_backfill(
        settings=MlConfig(),
        logger=Mock(),
        planner=Mock(spec=MlJobPlanner),
        job_store=job_store,
        cooldown_store=cooldown_store,
        handlers={},
        job_types=("create_article_card",),
    )

    assert run_cycle.await_args is not None
    assert run_cycle.await_args.kwargs["job_types"] == ("create_article_card",)
    job_store.summarize_jobs.assert_awaited_once_with(job_types=("create_article_card",))


@pytest.mark.asyncio
async def test_backfill_waits_for_deferred_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    run_cycle = AsyncMock(
        side_effect=[
            {"scanned_articles": 0, "ensured_jobs": 0, "processed_jobs": 0, "failed_jobs": 0},
            {"scanned_articles": 0, "ensured_jobs": 0, "processed_jobs": 1, "failed_jobs": 0},
        ]
    )
    sleep = AsyncMock()
    monkeypatch.setattr(execution, "run_cycle", run_cycle)
    monkeypatch.setattr(asyncio, "sleep", sleep)
    job_store = Mock(spec=ArticleJobStore)
    job_store.summarize_jobs = AsyncMock(
        side_effect=[
            JobQueueSummary(
                queued_jobs=1,
                running_jobs=0,
                blocked_jobs=0,
                failed_jobs=0,
                next_run_after=datetime(2026, 6, 11, 18, 0, tzinfo=UTC),
            ),
            JobQueueSummary(
                queued_jobs=0,
                running_jobs=0,
                blocked_jobs=0,
                failed_jobs=1,
                next_run_after=None,
            ),
        ]
    )
    cooldown_store = Mock(spec=LlmCooldownStore)
    cooldown_store.active_resume_at = AsyncMock(return_value=None)

    summary = await drain_backfill(
        settings=MlConfig(poll_interval_seconds=17),
        logger=Mock(),
        planner=Mock(spec=MlJobPlanner),
        job_store=job_store,
        cooldown_store=cooldown_store,
        handlers={},
    )

    sleep.assert_awaited_once_with(17)
    assert summary.failed_jobs == 1


@pytest.mark.asyncio
async def test_backfill_waits_through_active_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    run_cycle = AsyncMock(
        return_value={
            "scanned_articles": 0,
            "ensured_jobs": 0,
            "processed_jobs": 0,
            "failed_jobs": 0,
        }
    )
    sleep = AsyncMock()
    monkeypatch.setattr(execution, "run_cycle", run_cycle)
    monkeypatch.setattr(asyncio, "sleep", sleep)
    job_store = Mock(spec=ArticleJobStore)
    job_store.summarize_jobs = AsyncMock(
        return_value=JobQueueSummary(
            queued_jobs=0,
            running_jobs=0,
            blocked_jobs=0,
            failed_jobs=0,
            next_run_after=None,
        )
    )
    cooldown_store = Mock(spec=LlmCooldownStore)
    cooldown_store.active_resume_at = AsyncMock(
        side_effect=[datetime(2026, 6, 11, 18, 0, tzinfo=UTC), None, None]
    )

    await drain_backfill(
        settings=MlConfig(poll_interval_seconds=17),
        logger=Mock(),
        planner=Mock(spec=MlJobPlanner),
        job_store=job_store,
        cooldown_store=cooldown_store,
        handlers={},
    )

    sleep.assert_awaited_once_with(17)
    run_cycle.assert_awaited_once()


@pytest.mark.asyncio
async def test_backfill_returns_when_only_blocked_jobs_remain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        entrypoint,
        "run_cycle",
        AsyncMock(
            return_value={
                "scanned_articles": 0,
                "ensured_jobs": 0,
                "processed_jobs": 0,
                "failed_jobs": 0,
            }
        ),
    )
    job_store = Mock(spec=ArticleJobStore)
    job_store.summarize_jobs = AsyncMock(
        return_value=JobQueueSummary(
            queued_jobs=0,
            running_jobs=1,
            blocked_jobs=1,
            failed_jobs=0,
            next_run_after=None,
            blocked_running_jobs=1,
        )
    )
    cooldown_store = Mock(spec=LlmCooldownStore)
    cooldown_store.active_resume_at = AsyncMock(return_value=None)

    summary = await drain_backfill(
        settings=MlConfig(),
        logger=Mock(),
        planner=Mock(spec=MlJobPlanner),
        job_store=job_store,
        cooldown_store=cooldown_store,
        handlers={},
    )

    assert summary.blocked_jobs == 1


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
    monkeypatch.setattr(
        E5Embedder,
        "load",
        Mock(side_effect=AssertionError("idle worker loop should not load embeddings")),
    )
    monkeypatch.setattr(entrypoint, "create_async_engine_from_config", Mock(return_value=engine))
    monkeypatch.setattr(entrypoint, "create_async_sessionmaker", Mock())
    cooldown_store = Mock(spec=LlmCooldownStore)
    cooldown_store.active_resume_at = AsyncMock(return_value=None)
    monkeypatch.setattr(entrypoint, "LlmCooldownStore", Mock(return_value=cooldown_store))
    monkeypatch.setattr(entrypoint, "run_cycle", run_cycle)
    monkeypatch.setattr(entrypoint, "cleanup_stale_llm_runs", AsyncMock())
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


def test_resolution_candidate_limit_defaults() -> None:
    config = MlConfig()

    assert config.case_resolution_candidate_limit == 12
    assert config.entity_resolution_candidate_limit == 8
    assert config.event_resolution_candidate_limit == 8
    assert config.article_card_text_max_chars == 20_000
    assert config.llm_max_output_tokens == 4_096
    assert config.case_link_audit_card_limit == 20
    assert config.case_review_card_limit == 40
    assert config.case_copy_card_limit == 40


@pytest.mark.parametrize(
    "field_name",
    [
        "case_resolution_candidate_limit",
        "entity_resolution_candidate_limit",
        "event_resolution_candidate_limit",
        "article_card_text_max_chars",
        "llm_max_output_tokens",
        "case_audit_card_batch_size",
        "case_link_audit_card_limit",
        "case_review_card_limit",
        "case_copy_card_limit",
    ],
)
def test_resolution_candidate_limits_must_be_positive(field_name: str) -> None:
    with pytest.raises(ValueError):
        MlConfig.model_validate({field_name: 0})


def test_llm_config_defaults_to_litellm_proxy_aliases() -> None:
    fields = MlConfig.model_fields

    assert fields["llm_api_base"].default == "http://llm-proxy:4000/v1"
    assert fields["case_audit_card_batch_size"].default == 20
    assert fields["llm_article_card_model"].default == "shkandal-article-card"
    assert fields["llm_case_resolution_model"].default == "shkandal-case-resolution"
    assert fields["llm_entity_resolution_model"].default == "shkandal-entity-resolution"
    assert fields["llm_event_resolution_model"].default == "shkandal-event-resolution"
    assert fields["llm_case_copy_update_model"].default == "shkandal-case-copy-update"
    assert fields["llm_case_coherence_audit_model"].default == "shkandal-case-coherence-audit"
    assert (
        fields["llm_case_public_interest_audit_model"].default
        == "shkandal-case-public-interest-audit"
    )
    assert fields["llm_case_duplicate_audit_model"].default == "shkandal-case-duplicate-audit"
    assert fields["llm_repair_model"].default == "shkandal-repair"
    assert fields["llm_structured_output_mode"].default == "disabled"
    assert fields["case_audit_automatic_enabled"].default is True


def test_worker_concurrency_defaults_to_four() -> None:
    assert MlConfig.model_fields["worker_concurrency"].default == 4
