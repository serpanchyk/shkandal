"""Tests for dropped-link case-resolution job resets."""

from collections.abc import Sequence
from unittest.mock import AsyncMock, MagicMock, Mock
from uuid import uuid4

import pytest
import worker_ml.scripts.reset_unconnected_case_resolution_jobs as reset_cli
from worker_ml.scripts.reset_unconnected_case_resolution_jobs import (
    reset_unconnected_case_resolution_jobs,
)


def _session_context(session: MagicMock) -> MagicMock:
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=None)
    return context


def _execute_result(values: Sequence[object]) -> MagicMock:
    result = MagicMock()
    result.all.return_value = values
    return result


async def test_reset_unconnected_case_resolution_jobs_is_dry_run_by_default() -> None:
    job_id = uuid4()
    article_id = uuid4()
    session = MagicMock()
    session.execute = AsyncMock(return_value=_execute_result([(job_id, article_id)]))
    session.commit = AsyncMock()

    stats = await reset_unconnected_case_resolution_jobs(
        Mock(return_value=_session_context(session)),
        apply=False,
    )

    assert stats.selected_count == 1
    assert stats.selected_jobs[0].job_id == job_id
    assert stats.selected_jobs[0].article_id == article_id
    assert stats.applied is False
    session.commit.assert_not_awaited()
    query = session.execute.await_args.args[0]
    query_text = str(query)
    assert query.compile().params["job_type_1"] == "resolve_article_cases"
    assert query.compile().params["run_type_1"] == "case_link_audit"
    assert "jobs.status =" in query_text
    assert "article_cards.is_case_candidate IS true" in query_text
    assert "case_articles" in query_text


async def test_reset_selection_requires_no_case_article_and_link_audit() -> None:
    session = MagicMock()
    session.execute = AsyncMock(return_value=_execute_result([]))
    session.commit = AsyncMock()

    await reset_unconnected_case_resolution_jobs(
        Mock(return_value=_session_context(session)),
        apply=False,
        limit=10,
    )

    query_text = str(session.execute.await_args.args[0])
    assert "NOT (EXISTS" in query_text
    assert "case_articles.article_id = jobs.article_id" in query_text
    assert "llm_runs.run_type =" in query_text
    assert "llm_runs.metadata" in query_text
    assert "LIMIT" in query_text
    session.commit.assert_not_awaited()


async def test_reset_unconnected_case_resolution_jobs_applies_only_selected_jobs() -> None:
    selected_id = uuid4()
    article_id = uuid4()
    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=[
            _execute_result([(selected_id, article_id)]),
            MagicMock(),
        ]
    )
    session.commit = AsyncMock()

    stats = await reset_unconnected_case_resolution_jobs(
        Mock(return_value=_session_context(session)),
        apply=True,
    )

    assert stats.selected_count == 1
    reset = session.execute.await_args_list[1].args[0]
    params = reset.compile().params
    assert [selected_id] in params.values()
    assert params["status"] == "queued"
    assert params["attempt_count"] == 0
    assert params["run_after"] is None
    assert params["locked_at"] is None
    assert params["locked_by"] is None
    assert params["last_error"] is None
    session.commit.assert_awaited_once()


@pytest.mark.parametrize("limit", [0, -1])
async def test_reset_unconnected_case_resolution_jobs_rejects_non_positive_limit(
    limit: int,
) -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        await reset_unconnected_case_resolution_jobs(Mock(), apply=False, limit=limit)


def test_reset_cli_reports_database_timeout_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def timeout_run(*, apply: bool, limit: int | None) -> None:  # noqa: ARG001
        raise TimeoutError

    monkeypatch.setattr(reset_cli, "_run", timeout_run)
    monkeypatch.setattr(reset_cli, "_configured_database_target", lambda: ("127.0.0.1", 15432))
    monkeypatch.setattr("sys.argv", ["reset_unconnected_case_resolution_jobs"])

    with pytest.raises(SystemExit) as raised:
        reset_cli.main()

    assert raised.value.code == 2
    captured = capsys.readouterr()
    assert "could not connect to PostgreSQL at 127.0.0.1:15432" in captured.err
    assert "POSTGRES_DATABASE_URL" in captured.err
