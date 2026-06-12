"""Tests for ML job planning."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock
from uuid import uuid4

import pytest
from shkandal_database.jobs import BulkEnqueueJobResult
from worker_ml.classifier import RelevanceModel, build_classifier_text
from worker_ml.jobs import (
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
