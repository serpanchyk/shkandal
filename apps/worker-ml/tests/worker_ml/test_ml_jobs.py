"""Tests for ML job planning."""

from worker_ml.jobs import CLASSIFY_ARTICLE_JOB, EnqueueStats


def test_classify_article_job_type_is_stable() -> None:
    assert CLASSIFY_ARTICLE_JOB == "classify_article"


def test_enqueue_stats_names_idempotent_job_count() -> None:
    stats = EnqueueStats(scanned_articles=2, ensured_jobs=2)

    assert stats.ensured_jobs == 2
