"""Tests for ML job planning."""

from decimal import Decimal

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
    stats = EnqueueStats(scanned_articles=2, ensured_jobs=2)

    assert stats.ensured_jobs == 2


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
