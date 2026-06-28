from unittest.mock import AsyncMock, MagicMock, Mock
from uuid import uuid4

import pytest
import worker_ml.cases.refresh as case_refresh
from shkandal_database.jobs import ClaimedJob
from shkandal_database.models import Case
from worker_ml.cases.publication import case_vector_payload
from worker_ml.cases.refresh import RefreshCaseJobHandler
from worker_ml.llm.contracts import RefreshCaseOutput
from worker_ml.llm.runner import LlmTaskResult, LlmTaskRunner
from worker_ml.retrieval.vector_index import VectorIndexService


def _session_context(session: MagicMock) -> MagicMock:
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=None)
    return context


@pytest.mark.asyncio
async def test_refresh_case_updates_copy_vector_and_article_count_watermark(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = Case(
        id=uuid4(),
        slug="case-a",
        title_uk="Стара назва",
        summary_uk=None,
        status="active",
        article_count=4,
        event_count=0,
        last_refreshed_article_count=1,
        metadata_={},
    )
    output = RefreshCaseOutput.model_validate(
        {
            "title_diagnosis": {
                "current_title_specific_enough": False,
                "replacement_needed_reason_uk": "Назва була надто вузькою.",
                "proposed_title_core_uk": "Оновлена справа",
            },
            "replacement_title_uk": "Оновлена справа",
            "summary_uk": "Оновлений підсумок справи.",
            "title_reason_uk": "Назва уточнює стабільне ядро справи.",
            "title_action": "replace",
        }
    )
    session = MagicMock()
    session.scalar = AsyncMock(return_value=True)
    session.get = AsyncMock(return_value=case)
    session.commit = AsyncMock()
    runner = Mock(spec=LlmTaskRunner)
    runner.run_with_provenance = AsyncMock(
        return_value=LlmTaskResult(output=output, run_id=uuid4())
    )
    vector_index = Mock(spec=VectorIndexService)
    vector_index.upsert_case = AsyncMock()
    monkeypatch.setattr(case_refresh, "_case_article_cards", AsyncMock(return_value=[]))

    result = await RefreshCaseJobHandler(
        Mock(return_value=_session_context(session)),
        runner,
        vector_index,
        model_name="shkandal-refresh-case",
        card_limit=40,
    ).handle(
        ClaimedJob(
            id=uuid4(),
            job_type="refresh_case",
            article_id=None,
            case_id=case.id,
            payload={"case_id": str(case.id)},
            attempt_count=1,
            max_attempts=3,
        )
    )

    assert result == output
    assert case.title_uk == "Оновлена справа"
    assert case.summary_uk == "Оновлений підсумок справи."
    assert case.last_refreshed_article_count == 4
    vector_index.upsert_case.assert_awaited_once_with(case.id, case_vector_payload(case))
    session.commit.assert_awaited_once()
