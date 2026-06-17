from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, Mock
from uuid import UUID, uuid4

import pytest
import worker_ml.cases.resolution as case_resolution
from shkandal_database.jobs import ArticleJobStore, ClaimedJob
from shkandal_database.models import Article, ArticleCard, Case, Source
from worker_ml.cases.copy import lifecycle_sample
from worker_ml.cases.publication import case_vector_payload
from worker_ml.cases.resolution import (
    ArticleCaseResolutionJobHandler,
    _enqueue_resolution_followups,
    _filter_case_relations,
    _normalize_invalid_case_relations,
    _reject_resolution_after_link_audit,
    _relation_endpoint,
)
from worker_ml.llm.contracts import CaseLinkAuditOutput, CaseResolutionOutput
from worker_ml.llm.runner import LlmTaskResult, LlmTaskRunner
from worker_ml.retrieval.vector_index import VectorIndexService


def _session_context(session: MagicMock) -> MagicMock:
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=None)
    return context


def _link_audit_output(*, outcome: str) -> CaseLinkAuditOutput:
    diagnosis: dict[str, object] = {
        "article_story_core_uk": "Стаття описує той самий тендер.",
        "case_story_core_uk": "Справу утворює той самий тендер.",
        "shared_specific_core_uk": "Той самий тендер із підозрою в завищенні ціни.",
        "only_broad_overlap_uk": None,
        "disconnect_signals_uk": [],
        "coherence_test_uk": "Так, це один конкретний тендер.",
    }
    if outcome != "connect":
        diagnosis["shared_specific_core_uk"] = None
        diagnosis["disconnect_signals_uk"] = ["Це інша конкретна закупівля."]
    return CaseLinkAuditOutput.model_validate(
        {
            "diagnosis": diagnosis,
            "reason_uk": "Повторна перевірка дала однозначний висновок.",
            "outcome": outcome,
        }
    )


def test_lifecycle_sample_preserves_first_last_and_full_span() -> None:
    cards = [{"position": index} for index in range(100)]

    sample = lifecycle_sample(cards, 6)

    assert len(sample) == 6
    assert sample[0] == {"position": 0}
    assert sample[-1] == {"position": 99}
    assert [card["position"] for card in sample] == sorted(card["position"] for card in sample)


def test_relation_endpoint_resolves_new_ref_or_existing_uuid() -> None:
    new_case_id = uuid4()
    existing_case_id = uuid4()

    assert _relation_endpoint(None, "new_1", {"new_1": new_case_id}) == new_case_id
    assert _relation_endpoint(str(existing_case_id), None, {}) == existing_case_id


def test_invalid_optional_case_relations_are_discarded() -> None:
    candidate_id = uuid4()
    invalid_id = uuid4()
    output = CaseResolutionOutput.model_validate(
        {
            "diagnosis": {
                "article_story_core_uk": "Стаття описує дві конкретні пов'язані справи.",
                "specific_case_core_uk": "Окрема нова справа з цього ж матеріалу.",
                "only_broad_overlap_uk": None,
                "merge_blockers_uk": [],
                "separate_story_cores_uk": ["Наявна справа.", "Окрема нова справа."],
                "case_coherence_test_uk": "Так, кожна справа має конкретне ядро.",
                "matching_existing_case_ids": [str(candidate_id)],
                "new_case_core_uk": "Окрема нова справа з цього ж матеріалу.",
                "rejection_signals_uk": [],
                "broad_theme_warning_uk": None,
            },
            "decision_reason_uk": "Стаття описує дві пов'язані справи.",
            "outcome": "resolved",
            "existing_case_links": [
                {
                    "case_id": str(candidate_id),
                    "link_reason_uk": "Та сама справа.",
                    "confidence": 0.9,
                }
            ],
            "new_cases": [
                {
                    "new_case_ref": "new_case",
                    "title_uk": "Нова справа",
                    "summary_uk": "Опис.",
                    "link_reason_uk": "Окрема справа.",
                    "confidence": 0.8,
                }
            ],
            "case_relations": [
                {
                    "case_a_id": str(candidate_id),
                    "case_b_new_ref": "new_case",
                    "relation_type": "related",
                },
                {
                    "case_a_id": str(invalid_id),
                    "case_b_new_ref": "new_case",
                    "relation_type": "related",
                },
            ],
        }
    )

    normalized = _normalize_invalid_case_relations(output, {str(candidate_id)})

    assert normalized.existing_case_links == output.existing_case_links
    assert normalized.new_cases == output.new_cases
    assert normalized.case_relations == output.case_relations[:1]


@pytest.mark.asyncio
async def test_handler_stops_after_explicit_case_rejection() -> None:
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
        published_at=datetime(2026, 6, 15, tzinfo=UTC),
        fetch_status="succeeded",
    )
    card = ArticleCard(
        article_id=article.id,
        title_uk="Заголовок",
        summary_uk="Короткий опис.",
        is_case_candidate=True,
        card_json={},
    )
    session = MagicMock()
    session.scalar = AsyncMock(side_effect=[True, card])
    session.scalars = AsyncMock(return_value=MagicMock(all=lambda: []))
    article_result = MagicMock()
    article_result.one.return_value = (article, source)
    session.execute = AsyncMock(return_value=article_result)
    session.commit = AsyncMock()
    session_factory = Mock(return_value=_session_context(session))
    output = CaseResolutionOutput.model_validate(
        {
            "diagnosis": {
                "article_story_core_uk": None,
                "specific_case_core_uk": None,
                "only_broad_overlap_uk": None,
                "merge_blockers_uk": [],
                "separate_story_cores_uk": [],
                "case_coherence_test_uk": "Ні, немає конкретної відстежуваної справи.",
                "matching_existing_case_ids": [],
                "new_case_core_uk": None,
                "rejection_signals_uk": ["Немає конкретної відстежуваної справи."],
                "broad_theme_warning_uk": None,
            },
            "decision_reason_uk": "Матеріал не містить конкретної відстежуваної справи.",
            "outcome": "rejected",
        }
    )
    runner = Mock(spec=LlmTaskRunner)
    runner.run_with_provenance = AsyncMock(
        return_value=LlmTaskResult(output=output, run_id=uuid4())
    )
    job_store = Mock(spec=ArticleJobStore)
    job_store.enqueue_case_job = AsyncMock()
    job_store.enqueue_article_job = AsyncMock()
    vector_index = Mock(spec=VectorIndexService)
    vector_index.upsert_case = AsyncMock()
    handler = ArticleCaseResolutionJobHandler(
        session_factory,
        job_store,
        runner,
        vector_index,
        model_name="shkandal-case-resolution",
        candidate_limit=12,
    )
    handler._load_candidates = AsyncMock(return_value=[])  # type: ignore[method-assign]
    handler._persist_resolution = AsyncMock()  # type: ignore[method-assign]

    result = await handler.handle(
        ClaimedJob(
            id=uuid4(),
            job_type="resolve_article_cases",
            article_id=article.id,
            payload={"article_id": str(article.id)},
            attempt_count=1,
            max_attempts=3,
        )
    )

    assert result == output
    handler._persist_resolution.assert_not_awaited()
    vector_index.upsert_case.assert_not_awaited()
    session.commit.assert_not_awaited()
    job_store.enqueue_case_job.assert_not_awaited()
    job_store.enqueue_article_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_case_candidate_limit_is_forwarded_to_vector_search() -> None:
    vector_index = Mock(spec=VectorIndexService)
    vector_index.search_cases = AsyncMock(return_value=[])
    handler = ArticleCaseResolutionJobHandler(
        Mock(),
        Mock(),
        Mock(),
        vector_index,
        model_name="shkandal-case-resolution",
        candidate_limit=5,
    )
    card = ArticleCard(
        article_id=uuid4(),
        title_uk="Заголовок",
        summary_uk="Короткий опис.",
        is_case_candidate=True,
        card_json={},
    )

    assert await handler._load_candidates(Mock(), card) == []

    vector_index.search_cases.assert_awaited_once_with("Заголовок\nКороткий опис.", limit=5)


def test_case_payload_is_rebuildable_from_postgres_case() -> None:
    case_id = UUID("00000000-0000-0000-0000-000000000001")
    case = Case(
        id=case_id,
        slug="case-a",
        title_uk="Назва",
        summary_uk="Опис",
        status="active",
        article_count=3,
        event_count=2,
        metadata_={"source": "test"},
    )

    payload = case_vector_payload(case)

    assert payload.title_uk == "Назва"
    assert payload.article_count == 3
    assert payload.metadata == {"source": "test"}


@pytest.mark.asyncio
async def test_resolution_followups_are_idempotently_ensured() -> None:
    article_id = uuid4()
    case_ids = {uuid4(), uuid4()}
    job_store = Mock(spec=ArticleJobStore)
    job_store.enqueue_case_job = AsyncMock()
    job_store.enqueue_article_job = AsyncMock()

    await _enqueue_resolution_followups(
        job_store=job_store,
        job=ClaimedJob(
            id=uuid4(),
            job_type="resolve_article_case",
            article_id=article_id,
            payload={},
            attempt_count=1,
            max_attempts=3,
        ),
        case_ids=case_ids,
    )

    assert job_store.enqueue_case_job.await_count == 2
    assert job_store.enqueue_article_job.await_count == 2
    assert {call.kwargs["job_type"] for call in job_store.enqueue_article_job.await_args_list} == {
        "resolve_article_entities",
        "resolve_article_events",
    }


def test_filter_case_relations_drops_removed_existing_case_links() -> None:
    output = CaseResolutionOutput.model_validate(
        {
            "diagnosis": {
                "article_story_core_uk": "Стаття описує дві конкретні пов'язані справи.",
                "specific_case_core_uk": "Конкретне ядро справи.",
                "only_broad_overlap_uk": None,
                "merge_blockers_uk": [],
                "separate_story_cores_uk": ["Перша історія.", "Друга історія."],
                "case_coherence_test_uk": "Так, окремі справи конкретні.",
                "matching_existing_case_ids": ["case-a", "case-b"],
                "new_case_core_uk": None,
                "rejection_signals_uk": [],
                "broad_theme_warning_uk": None,
            },
            "decision_reason_uk": "Стаття описує дві пов'язані справи.",
            "outcome": "resolved",
            "existing_case_links": [
                {"case_id": "case-a", "link_reason_uk": "Перша справа.", "confidence": 0.9},
                {"case_id": "case-b", "link_reason_uk": "Друга справа.", "confidence": 0.9},
            ],
            "new_cases": [
                {
                    "new_case_ref": "new_case",
                    "title_uk": "Нова справа",
                    "summary_uk": "Опис.",
                    "link_reason_uk": "Нова пов'язана справа.",
                    "confidence": 0.8,
                }
            ],
            "case_relations": [
                {"case_a_id": "case-a", "case_b_id": "case-b", "relation_type": "related"},
                {"case_a_id": "case-a", "case_b_new_ref": "new_case", "relation_type": "related"},
            ],
        }
    )

    filtered = _filter_case_relations(output.case_relations, {"case-a"})

    assert len(filtered) == 1
    assert filtered[0].case_a_id == "case-a"
    assert filtered[0].case_b_new_ref == "new_case"


def test_reject_resolution_after_link_audit_rewrites_to_rejected() -> None:
    output = CaseResolutionOutput.model_validate(
        {
            "diagnosis": {
                "article_story_core_uk": "Стаття описує конкретну закупівельну історію.",
                "specific_case_core_uk": "Конкретне ядро закупівлі.",
                "only_broad_overlap_uk": None,
                "merge_blockers_uk": [],
                "separate_story_cores_uk": [],
                "case_coherence_test_uk": "Так, історія конкретна.",
                "matching_existing_case_ids": ["case-a"],
                "new_case_core_uk": None,
                "rejection_signals_uk": [],
                "broad_theme_warning_uk": None,
            },
            "decision_reason_uk": "Первинний матчінг знайшов одну справу.",
            "outcome": "resolved",
            "existing_case_links": [
                {"case_id": "case-a", "link_reason_uk": "Схожа справа.", "confidence": 0.7}
            ],
            "new_cases": [],
            "case_relations": [],
        }
    )

    rejected = _reject_resolution_after_link_audit(output)

    assert rejected.outcome == "rejected"
    assert not rejected.existing_case_links
    assert rejected.diagnosis.matching_existing_case_ids == []
    assert rejected.diagnosis.rejection_signals_uk[-1].startswith("Жодна наявна справа")


@pytest.mark.asyncio
async def test_link_recheck_keeps_only_connecting_existing_cases() -> None:
    article = Article(
        id=uuid4(),
        source_id=uuid4(),
        url="https://example.com/article",
        identity_url="https://example.com/article",
        title="Заголовок",
        fetch_status="succeeded",
    )
    card = ArticleCard(
        article_id=article.id,
        title_uk="Заголовок",
        summary_uk="Короткий опис.",
        is_case_candidate=True,
        card_json={},
    )
    keep_case = Case(
        id=uuid4(),
        slug="case-keep",
        title_uk="Справa 1",
        summary_uk="Опис 1",
        status="active",
    )
    drop_case = Case(
        id=uuid4(),
        slug="case-drop",
        title_uk="Справa 2",
        summary_uk="Опис 2",
        status="active",
    )
    session = MagicMock()
    session.get = AsyncMock(side_effect=[keep_case, drop_case])
    session_factory = Mock(return_value=_session_context(session))
    handler = ArticleCaseResolutionJobHandler(
        session_factory,
        Mock(spec=ArticleJobStore),
        Mock(spec=LlmTaskRunner),
        Mock(spec=VectorIndexService),
        model_name="shkandal-case-resolution",
        candidate_limit=12,
    )
    handler._run_case_link_audit = AsyncMock(  # type: ignore[method-assign]
        side_effect=[_link_audit_output(outcome="connect"), _link_audit_output(outcome="drop")]
    )
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        case_resolution,
        "load_case_article_cards",
        AsyncMock(return_value=[{"article_id": "existing"}]),
    )

    output = CaseResolutionOutput.model_validate(
        {
            "diagnosis": {
                "article_story_core_uk": "Стаття описує дві схожі закупівельні історії.",
                "specific_case_core_uk": "Конкретна закупівля.",
                "only_broad_overlap_uk": None,
                "merge_blockers_uk": [],
                "separate_story_cores_uk": [],
                "case_coherence_test_uk": "Так, щонайменше одна конкретна справа є.",
                "matching_existing_case_ids": [str(keep_case.id), str(drop_case.id)],
                "new_case_core_uk": None,
                "rejection_signals_uk": [],
                "broad_theme_warning_uk": None,
            },
            "decision_reason_uk": "Первинний матчінг знайшов дві справи.",
            "outcome": "resolved",
            "existing_case_links": [
                {
                    "case_id": str(keep_case.id),
                    "link_reason_uk": "Перша справа.",
                    "confidence": 0.9,
                },
                {
                    "case_id": str(drop_case.id),
                    "link_reason_uk": "Друга справа.",
                    "confidence": 0.8,
                },
            ],
            "new_cases": [],
            "case_relations": [
                {
                    "case_a_id": str(keep_case.id),
                    "case_b_id": str(drop_case.id),
                    "relation_type": "related",
                }
            ],
        }
    )

    filtered = await handler._recheck_existing_case_links(
        session,
        job=ClaimedJob(
            id=uuid4(),
            job_type="resolve_article_cases",
            article_id=article.id,
            payload={},
            attempt_count=1,
            max_attempts=3,
        ),
        article=article,
        card=card,
        output=output,
        candidates=[
            {
                "case_id": str(keep_case.id),
                "score": 0.9,
                "title_uk": keep_case.title_uk,
                "summary_uk": keep_case.summary_uk,
                "evidence_titles": ["Один"],
            },
            {
                "case_id": str(drop_case.id),
                "score": 0.8,
                "title_uk": drop_case.title_uk,
                "summary_uk": drop_case.summary_uk,
                "evidence_titles": ["Два"],
            },
        ],
    )

    assert [link.case_id for link in filtered.existing_case_links] == [str(keep_case.id)]
    assert filtered.case_relations == []
    monkeypatch.undo()


@pytest.mark.asyncio
async def test_link_recheck_turns_resolution_into_rejection_when_all_existing_cases_drop() -> None:
    article = Article(
        id=uuid4(),
        source_id=uuid4(),
        url="https://example.com/article",
        identity_url="https://example.com/article",
        title="Заголовок",
        fetch_status="succeeded",
    )
    card = ArticleCard(
        article_id=article.id,
        title_uk="Заголовок",
        summary_uk="Короткий опис.",
        is_case_candidate=True,
        card_json={},
    )
    case = Case(
        id=uuid4(),
        slug="case-drop",
        title_uk="Справa",
        summary_uk="Опис",
        status="active",
    )
    session = MagicMock()
    session.get = AsyncMock(return_value=case)
    session_factory = Mock(return_value=_session_context(session))
    handler = ArticleCaseResolutionJobHandler(
        session_factory,
        Mock(spec=ArticleJobStore),
        Mock(spec=LlmTaskRunner),
        Mock(spec=VectorIndexService),
        model_name="shkandal-case-resolution",
        candidate_limit=12,
    )
    handler._run_case_link_audit = AsyncMock(  # type: ignore[method-assign]
        return_value=_link_audit_output(outcome="inconclusive")
    )
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        case_resolution,
        "load_case_article_cards",
        AsyncMock(return_value=[{"article_id": "existing"}]),
    )

    output = CaseResolutionOutput.model_validate(
        {
            "diagnosis": {
                "article_story_core_uk": "Стаття описує конкретну закупівлю.",
                "specific_case_core_uk": "Конкретна закупівля.",
                "only_broad_overlap_uk": None,
                "merge_blockers_uk": [],
                "separate_story_cores_uk": [],
                "case_coherence_test_uk": "Так, історія конкретна.",
                "matching_existing_case_ids": [str(case.id)],
                "new_case_core_uk": None,
                "rejection_signals_uk": [],
                "broad_theme_warning_uk": None,
            },
            "decision_reason_uk": "Первинний матчінг знайшов одну справу.",
            "outcome": "resolved",
            "existing_case_links": [
                {"case_id": str(case.id), "link_reason_uk": "Справa.", "confidence": 0.9}
            ],
            "new_cases": [],
            "case_relations": [],
        }
    )

    filtered = await handler._recheck_existing_case_links(
        session,
        job=ClaimedJob(
            id=uuid4(),
            job_type="resolve_article_cases",
            article_id=article.id,
            payload={},
            attempt_count=1,
            max_attempts=3,
        ),
        article=article,
        card=card,
        output=output,
        candidates=[
            {
                "case_id": str(case.id),
                "score": 0.9,
                "title_uk": case.title_uk,
                "summary_uk": case.summary_uk,
                "evidence_titles": ["Один"],
            }
        ],
    )

    assert filtered.outcome == "rejected"
    monkeypatch.undo()
