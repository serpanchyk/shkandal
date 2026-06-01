from datetime import datetime

from worker_ingestion.main import _parse_datetime


def test_parse_datetime_uses_iso_format() -> None:
    assert _parse_datetime("2026-06-01T12:30:00+00:00") == datetime.fromisoformat(
        "2026-06-01T12:30:00+00:00"
    )
