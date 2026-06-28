import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, Mock
from uuid import uuid4

import pytest
from shkandal_database.jobs import ClaimedJob
from shkandal_database.models import Article, Source
from worker_ml.articles.gates import ArticleGateJobHandler
from worker_ml.llm.contracts import ArticleGateOutput
from worker_ml.llm.runner import LlmTaskResult, LlmTaskRunner
from worker_ml.llm.schema import prompt_schema


def _session_context(session: MagicMock) -> MagicMock:
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=None)
    return context


def _article_and_source() -> tuple[Article, Source]:
    source = Source(
        id=uuid4(),
        slug="example",
        name="Приклад",
        source_type="media",
        base_url="https://example.com",
    )
    article = Article(
        id=uuid4(),
        source_id=source.id,
        url="https://example.com/article",
        identity_url="https://example.com/article",
        title="Заголовок",
        lead="Лід",
        published_at=datetime(2026, 6, 6, 10, 0, tzinfo=UTC),
        extracted_text="Текст статті",
        fetch_status="succeeded",
    )
    return article, source


def _job(article: Article) -> ClaimedJob:
    return ClaimedJob(
        id=uuid4(),
        job_type="gate_article",
        article_id=article.id,
        payload={"article_id": str(article.id)},
        attempt_count=1,
        max_attempts=3,
    )


def _accepted_output() -> ArticleGateOutput:
    return ArticleGateOutput.model_validate(
        {
            "case_diagnosis": {
                "ukraine_nexus_uk": "Подія стосується українського регулятора.",
                "concrete_story_core_uk": "НБУ оштрафував банк у конкретній справі.",
                "public_accountability_anchor_uk": "Йдеться про дії державного регулятора.",
                "continuation_potential_uk": "Можливі подальші рішення або оскарження.",
                "noise_signals_uk": [],
            },
            "noise_reason": None,
            "case_decision_reason_uk": "Матеріал описує конкретну регуляторну справу.",
            "is_case_candidate": True,
        }
    )


@pytest.mark.asyncio
async def test_handler_persists_gate_and_enqueues_card_for_candidate() -> None:
    article, source = _article_and_source()
    read_session = MagicMock()
    read_result = MagicMock()
    read_result.one_or_none.return_value = (article, source, True, None, None)
    read_session.execute = AsyncMock(return_value=read_result)
    write_session = MagicMock()
    write_session.commit = AsyncMock()
    write_session.rollback = AsyncMock()
    write_session.execute = AsyncMock()
    session_factory = Mock(
        side_effect=[_session_context(read_session), _session_context(write_session)]
    )
    output = _accepted_output()
    run_id = uuid4()
    runner = Mock(spec=LlmTaskRunner)
    runner.run_with_provenance = AsyncMock(return_value=LlmTaskResult(output=output, run_id=run_id))
    job_store = Mock()
    job_store.enqueue_article_job = AsyncMock()

    result = await ArticleGateJobHandler(
        session_factory,
        runner,
        job_store,
        model_name="shkandal-article-gate",
        text_max_chars=20_000,
    ).handle(_job(article))

    assert result == output
    call = runner.run_with_provenance.await_args.kwargs
    assert call["run_type"] == "article_gate"
    assert call["model_name"] == "shkandal-article-gate"
    assert json.loads(call["variables"]["schema_json"]) == prompt_schema(ArticleGateOutput)
    params = write_session.execute.await_args.args[0].compile().params
    assert params["article_id"] == article.id
    assert params["llm_run_id"] == run_id
    assert params["is_case_candidate"] is True
    assert params["case_diagnosis"] == output.case_diagnosis.model_dump(mode="json")
    job_store.enqueue_article_job.assert_awaited_once()
    assert job_store.enqueue_article_job.await_args.kwargs["job_type"] == "create_article_card"


@pytest.mark.asyncio
async def test_handler_stops_after_rejected_gate() -> None:
    article, source = _article_and_source()
    read_session = MagicMock()
    read_result = MagicMock()
    read_result.one_or_none.return_value = (article, source, True, None, None)
    read_session.execute = AsyncMock(return_value=read_result)
    write_session = MagicMock()
    write_session.commit = AsyncMock()
    write_session.rollback = AsyncMock()
    write_session.execute = AsyncMock()
    session_factory = Mock(
        side_effect=[_session_context(read_session), _session_context(write_session)]
    )
    output = ArticleGateOutput.model_validate(
        {
            "case_diagnosis": {
                "ukraine_nexus_uk": None,
                "concrete_story_core_uk": None,
                "public_accountability_anchor_uk": None,
                "continuation_potential_uk": None,
                "noise_signals_uk": ["Рутинна дипломатична новина."],
            },
            "noise_reason": "diplomacy",
            "case_decision_reason_uk": "Матеріал не описує окрему справу.",
            "is_case_candidate": False,
        }
    )
    runner = Mock(spec=LlmTaskRunner)
    runner.run_with_provenance = AsyncMock(
        return_value=LlmTaskResult(output=output, run_id=uuid4())
    )
    job_store = Mock()
    job_store.enqueue_article_job = AsyncMock()

    await ArticleGateJobHandler(
        session_factory,
        runner,
        job_store,
        model_name="shkandal-article-gate",
        text_max_chars=20_000,
    ).handle(_job(article))

    job_store.enqueue_article_job.assert_not_awaited()
