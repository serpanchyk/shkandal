from datetime import datetime

from worker_ingestion.main import _parse_datetime, _parse_until_datetime


def test_parse_datetime_uses_iso_format() -> None:
    assert _parse_datetime("2026-06-01T12:30:00+00:00") == datetime.fromisoformat(
        "2026-06-01T12:30:00+00:00"
    )


def test_parse_until_datetime_includes_date_only_day() -> None:
    assert _parse_until_datetime("2026-06-03") == datetime.fromisoformat(
        "2026-06-03T23:59:59.999999"
    )


def test_parse_until_datetime_preserves_explicit_time() -> None:
    assert _parse_until_datetime("2026-06-03T12:30:00+00:00") == datetime.fromisoformat(
        "2026-06-03T12:30:00+00:00"
    )
