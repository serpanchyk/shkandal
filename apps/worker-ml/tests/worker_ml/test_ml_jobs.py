"""Tests for ML job planning."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock
from uuid import uuid4

import pytest
from shkandal_database.jobs import ArticleJobStore, BulkEnqueueJobResult
from worker_ml.articles.relevance import RelevanceModel, build_classifier_text
from worker_ml.runtime.planning import (
    AUDIT_CASE_COHERENCE_JOB,
    CLASSIFY_ARTICLE_JOB,
    CREATE_ARTICLE_CARD_JOB,
    EnqueueStats,
    MlJobPlanner,
)


def test_classify_article_job_type_is_stable() -> None:
    assert CLASSIFY_ARTICLE_JOB == "classify_article"
    assert CREATE_ARTICLE_CARD_JOB == "create_article_card"


def test_enqueue_stats_names_idempotent_job_count() -> None:
    stats = EnqueueStats(
        scanned_articles=3,
        ensured_jobs=2,
        inserted_jobs=1,
        requeued_jobs=1,
        existing_jobs=1,
    )

    assert stats.ensured_jobs == 2
    assert stats.existing_jobs == 1


@pytest.mark.asyncio
async def test_job_planner_counts_only_inserted_and_requeued_jobs() -> None:
    article_ids = [uuid4(), uuid4(), uuid4()]
    session = MagicMock()
    session.scalars = AsyncMock(return_value=SimpleNamespace(all=lambda: article_ids))
    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=None)
    session_factory = Mock(return_value=session_context)
    job_store = Mock()
    job_store.enqueue_article_jobs = AsyncMock(
        return_value=BulkEnqueueJobResult(
            inserted_jobs=1,
            requeued_jobs=1,
            existing_jobs=1,
        )
    )

    stats = await MlJobPlanner(session_factory, job_store).enqueue_missing_classification_jobs(
        limit=3,
        max_attempts=4,
    )

    assert stats == EnqueueStats(
        scanned_articles=3,
        ensured_jobs=2,
        inserted_jobs=1,
        requeued_jobs=1,
        existing_jobs=1,
    )


@pytest.mark.asyncio
async def test_job_planner_enqueues_missing_article_cards() -> None:
    article_ids = [uuid4(), uuid4()]
    session = MagicMock()
    session.scalars = AsyncMock(return_value=SimpleNamespace(all=lambda: article_ids))
    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=None)
    session_factory = Mock(return_value=session_context)
    job_store = Mock()
    job_store.enqueue_article_jobs = AsyncMock(
        return_value=BulkEnqueueJobResult(
            inserted_jobs=1,
            requeued_jobs=0,
            existing_jobs=1,
        )
    )

    stats = await MlJobPlanner(session_factory, job_store).enqueue_missing_article_card_jobs(
        limit=2,
        max_attempts=4,
        requeue_failed=False,
    )

    assert stats == EnqueueStats(
        scanned_articles=2,
        ensured_jobs=1,
        inserted_jobs=1,
        existing_jobs=1,
    )
    assert job_store.enqueue_article_jobs.await_args.kwargs == {
        "job_type": CREATE_ARTICLE_CARD_JOB,
        "article_ids": article_ids,
        "max_attempts": 4,
        "requeue_failed": False,
    }


@pytest.mark.asyncio
async def test_job_planner_can_preserve_exhausted_jobs_for_backfill() -> None:
    article_id = uuid4()
    session = MagicMock()
    session.scalars = AsyncMock(return_value=SimpleNamespace(all=lambda: [article_id]))
    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=None)
    session_factory = Mock(return_value=session_context)
    job_store = Mock()
    job_store.enqueue_article_jobs = AsyncMock(
        return_value=BulkEnqueueJobResult(
            inserted_jobs=0,
            requeued_jobs=0,
            existing_jobs=1,
        )
    )

    await MlJobPlanner(session_factory, job_store).enqueue_missing_classification_jobs(
        limit=10,
        max_attempts=3,
        requeue_failed=False,
    )

    assert job_store.enqueue_article_jobs.await_args.kwargs["requeue_failed"] is False


def test_job_planner_only_selects_successfully_fetched_articles() -> None:
    query = MlJobPlanner._articles_missing_relevance_query(limit=10)

    assert "articles.fetch_status" in str(query)


def test_missing_card_query_selects_only_relevant_articles_without_cards() -> None:
    query = str(MlJobPlanner._articles_missing_card_query(limit=10))

    assert "article_relevance.is_relevant IS true" in query
    assert "article_cards.id IS NULL" in query


@pytest.mark.asyncio
async def test_job_planner_enqueues_due_case_audits_without_revision_bumps() -> None:
    case_ids = [uuid4(), uuid4()]
    session = AsyncMock()
    session.scalars = AsyncMock(return_value=SimpleNamespace(all=lambda: case_ids))
    session_context = AsyncMock()
    session_context.__aenter__.return_value = session
    session_factory = Mock(return_value=session_context)
    job_store = Mock(spec=ArticleJobStore)
    job_store.ensure_case_job = AsyncMock(
        side_effect=[
            SimpleNamespace(state="inserted"),
            SimpleNamespace(state="existing"),
        ]
    )

    stats = await MlJobPlanner(session_factory, job_store).enqueue_due_case_audit_jobs(
        limit=2,
        max_attempts=3,
        interval_days=30,
    )

    assert stats.scanned_articles == 2
    assert stats.inserted_jobs == 1
    assert stats.existing_jobs == 1
    assert all(
        call.kwargs["job_type"] == AUDIT_CASE_COHERENCE_JOB
        for call in job_store.ensure_case_job.await_args_list
    )


@pytest.mark.asyncio
async def test_job_planner_requests_new_revisions_for_coherent_successful_audits() -> None:
    case_ids = [uuid4(), uuid4()]
    session = AsyncMock()
    session.scalars = AsyncMock(return_value=SimpleNamespace(all=lambda: case_ids))
    session_context = AsyncMock()
    session_context.__aenter__.return_value = session
    session_factory = Mock(return_value=session_context)
    job_store = Mock(spec=ArticleJobStore)
    job_store.enqueue_case_job = AsyncMock(
        side_effect=[
            SimpleNamespace(state="requeued"),
            SimpleNamespace(state="requeued"),
        ]
    )

    stats = await MlJobPlanner(
        session_factory, job_store
    ).enqueue_coherent_successful_case_audit_reruns(
        limit=2,
        max_attempts=3,
    )

    assert stats.scanned_articles == 2
    assert stats.requeued_jobs == 2
    assert all(
        call.kwargs["job_type"] == AUDIT_CASE_COHERENCE_JOB
        for call in job_store.enqueue_case_job.await_args_list
    )


def test_classifier_text_matches_training_format() -> None:
    result = build_classifier_text(
        title=" Заголовок ",
        extracted_text=" Текст статті. ",
    )

    assert result == "Заголовок\n\nТекст статті."


def test_classifier_text_allows_missing_title() -> None:
    result = build_classifier_text(title=None, extracted_text=" Текст статті. ")

    assert result == "Текст статті."


def test_missing_text_prediction_is_irrelevant() -> None:
    model = RelevanceModel(
        pipeline=_NeverCalledModel(),
        classifier_name="test",
        classifier_version="v1",
        threshold=0.5,
        positive_class_index=0,
    )

    prediction = model.predict(title="Title", extracted_text=None)

    assert prediction.is_relevant is False
    assert prediction.score == Decimal("0")
    assert prediction.metadata["reason"] == "missing_extracted_text"


class _NeverCalledModel:
    classes_ = ["assigned", "noise"]

    def predict_proba(self, texts: list[str]) -> list[list[float]]:
        raise AssertionError("missing-text articles should not call the model")
