import worker_ingestion


def test_package_imports() -> None:
    assert worker_ingestion.__doc__ is not None
