import importlib.util

import worker_ingestion


def test_package_imports() -> None:
    assert worker_ingestion.__doc__ is not None


def test_production_package_excludes_article_coverage_reporting() -> None:
    assert importlib.util.find_spec("worker_ingestion.article_coverage") is None
