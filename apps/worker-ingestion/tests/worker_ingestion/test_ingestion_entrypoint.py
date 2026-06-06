import sys
from datetime import datetime
from unittest.mock import AsyncMock

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


def test_no_args_dispatches_one_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    run_once = AsyncMock()
    monkeypatch.setattr(sys, "argv", ["worker-ingestion"])
    monkeypatch.setattr(entrypoint, "run_once", run_once)

    entrypoint.main()

    run_once.assert_awaited_once_with(
        source_slug=None,
        limit=None,
        since=None,
        until=None,
        max_backfill_urls_per_source=None,
    )


def test_targeted_args_dispatch_one_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    run_once = AsyncMock()
    monkeypatch.setattr(sys, "argv", ["worker-ingestion", "--source", "pravda", "--limit", "20"])
    monkeypatch.setattr(entrypoint, "run_once", run_once)

    entrypoint.main()

    run_once.assert_awaited_once_with(
        source_slug="pravda",
        limit=20,
        since=None,
        until=None,
        max_backfill_urls_per_source=None,
    )


def test_loop_flag_dispatches_continuous_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    run_continuously = AsyncMock()
    monkeypatch.setattr(sys, "argv", ["worker-ingestion", "--loop"])
    monkeypatch.setattr(entrypoint, "run_continuously", run_continuously)

    entrypoint.main()

    run_continuously.assert_awaited_once()


def test_repair_mode_still_dispatches_repair(monkeypatch: pytest.MonkeyPatch) -> None:
    repair_published_at = AsyncMock()
    monkeypatch.setattr(
        sys,
        "argv",
        ["worker-ingestion", "--repair-missing-published-at", "--source", "pravda"],
    )
    monkeypatch.setattr(entrypoint, "repair_published_at", repair_published_at)

    entrypoint.main()

    repair_published_at.assert_awaited_once_with(
        source_slug="pravda",
        limit=None,
        batch_size=500,
        apply=False,
    )
