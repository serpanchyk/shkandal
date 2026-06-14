import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, Mock
from uuid import uuid4

import pytest
from shkandal_database.jobs import ClaimedJob
from shkandal_database.models import Article, Source
from worker_ml.article_cards import (
    MAX_ARTICLE_TEXT_CHARACTERS,
    ArticleCardJobHandler,
    build_article_json,
    get_case_candidate_card,
)
from worker_ml.llm.contracts import ArticleCardOutput, ProvisionalEvent
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
        job_type="create_article_card",
        article_id=article.id,
        payload={"article_id": str(article.id)},
        attempt_count=1,
        max_attempts=3,
    )


@pytest.mark.asyncio
async def test_handler_creates_article_card_from_valid_llm_output() -> None:
    article, source = _article_and_source()
    read_session = MagicMock()
    read_result = MagicMock()
    read_result.one_or_none.return_value = (article, source, True, None)
    read_session.execute = AsyncMock(return_value=read_result)
    write_session = MagicMock()
    write_session.commit = AsyncMock()
    write_session.rollback = AsyncMock()
    write_session.execute = AsyncMock()
    session_factory = Mock(
        side_effect=[_session_context(read_session), _session_context(write_session)]
    )
    output = ArticleCardOutput(
        title_uk="Картка",
        summary_uk="Короткий опис",
        is_case_candidate=True,
        main_event_title_uk="НБУ оштрафував банк",
        entities=[],
        events=[
            ProvisionalEvent(
                provisional_ref="event_nbu_fine",
                title_uk="НБУ оштрафував банк",
                description_uk="Регулятор наклав штраф.",
                event_date="2026-06-06",
                event_date_precision="day",
            )
        ],
        case_signature_terms=["НБУ", "штраф"],
    )
    run_id = uuid4()
    runner = Mock(spec=LlmTaskRunner)
    runner.run_with_provenance = AsyncMock(return_value=LlmTaskResult(output=output, run_id=run_id))

    result = await ArticleCardJobHandler(
        session_factory,
        runner,
        model_name="shkandal-article-card",
    ).handle(_job(article))

    assert result == output
    runner.run_with_provenance.assert_awaited_once()
    call = runner.run_with_provenance.await_args.kwargs
    assert call["run_type"] == "article_card"
    assert call["model_name"] == "shkandal-article-card"
    assert json.loads(call["variables"]["schema_json"]) == prompt_schema(ArticleCardOutput)
    insert_statement = write_session.execute.await_args.args[0]
    params = insert_statement.compile().params
    assert params["article_id"] == article.id
    assert params["llm_run_id"] == run_id
    assert params["title_uk"] == "Картка"
    assert params["summary_uk"] == "Короткий опис"
    assert params["is_case_candidate"] is True
    assert params["card_json"] == output.model_dump(
        mode="json",
        exclude={"is_case_candidate"},
    )


@pytest.mark.asyncio
async def test_handler_persists_non_case_card_without_case_signals() -> None:
    article, source = _article_and_source()
    read_session = MagicMock()
    read_result = MagicMock()
    read_result.one_or_none.return_value = (article, source, True, None)
    read_session.execute = AsyncMock(return_value=read_result)
    write_session = MagicMock()
    write_session.commit = AsyncMock()
    write_session.rollback = AsyncMock()
    write_session.execute = AsyncMock()
    session_factory = Mock(
        side_effect=[_session_context(read_session), _session_context(write_session)]
    )
    output = ArticleCardOutput(
        title_uk="Словаччина підтримала переговори з ЄС",
        summary_uk="Словаччина заявила про підтримку переговорів.",
        is_case_candidate=False,
        noise_reason="diplomacy",
    )
    runner = Mock(spec=LlmTaskRunner)
    runner.run_with_provenance = AsyncMock(
        return_value=LlmTaskResult(output=output, run_id=uuid4())
    )

    await ArticleCardJobHandler(
        session_factory,
        runner,
        model_name="shkandal-article-card",
    ).handle(_job(article))

    statement = write_session.execute.await_args.args[0]
    params = statement.compile().params
    assert params["is_case_candidate"] is False
    assert params["card_json"]["entities"] == []
    assert params["card_json"]["events"] == []
    assert params["card_json"]["case_signature_terms"] == []


@pytest.mark.asyncio
async def test_case_candidate_gate_filters_on_persisted_column() -> None:
    article, _ = _article_and_source()
    expected_card = Mock()
    session = MagicMock()
    session.scalar = AsyncMock(return_value=expected_card)

    result = await get_case_candidate_card(session, article_id=article.id)

    assert result is expected_card
    statement = session.scalar.await_args.args[0]
    assert "article_cards.is_case_candidate IS true" in str(statement)


@pytest.mark.asyncio
async def test_handler_does_not_call_llm_for_irrelevant_article() -> None:
    article, source = _article_and_source()
    session = MagicMock()
    result = MagicMock()
    result.one_or_none.return_value = (article, source, False, None)
    session.execute = AsyncMock(return_value=result)
    session_factory = Mock(return_value=_session_context(session))
    runner = Mock(spec=LlmTaskRunner)
    runner.run_with_provenance = AsyncMock()

    handled = await ArticleCardJobHandler(
        session_factory,
        runner,
        model_name="shkandal-article-card",
    ).handle(_job(article))

    assert handled is None
    runner.run_with_provenance.assert_not_awaited()


@pytest.mark.asyncio
async def test_handler_does_not_call_llm_when_article_card_exists() -> None:
    article, source = _article_and_source()
    session = MagicMock()
    result = MagicMock()
    result.one_or_none.return_value = (article, source, True, uuid4())
    session.execute = AsyncMock(return_value=result)
    session_factory = Mock(return_value=_session_context(session))
    runner = Mock(spec=LlmTaskRunner)
    runner.run_with_provenance = AsyncMock()

    handled = await ArticleCardJobHandler(
        session_factory,
        runner,
        model_name="shkandal-article-card",
    ).handle(_job(article))

    assert handled is None
    runner.run_with_provenance.assert_not_awaited()


def test_build_article_json_limits_extracted_text() -> None:
    article, source = _article_and_source()
    article.extracted_text = "x" * (MAX_ARTICLE_TEXT_CHARACTERS + 10)

    payload = json.loads(build_article_json(article=article, source=source))

    assert len(payload["extracted_text"]) == MAX_ARTICLE_TEXT_CHARACTERS
    assert payload["source"] == {
        "name": "Приклад",
        "slug": "example",
        "source_type": "media",
    }
