import asyncio
import sys
from datetime import datetime

import pytest
import worker_ingestion.main as entrypoint
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


def test_targeted_run_requires_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["worker-ingestion", "--source", "pravda"])

    with pytest.raises(SystemExit) as exc_info:
        entrypoint.main()

    assert exc_info.value.code == 2


def test_once_flag_dispatches_one_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []

    def run(coroutine: object) -> None:
        called.append(coroutine.cr_code.co_name)  # type: ignore[attr-defined]
        coroutine.close()  # type: ignore[attr-defined]

    monkeypatch.setattr(sys, "argv", ["worker-ingestion", "--once"])
    monkeypatch.setattr(asyncio, "run", run)

    entrypoint.main()

    assert called == ["run_once"]
