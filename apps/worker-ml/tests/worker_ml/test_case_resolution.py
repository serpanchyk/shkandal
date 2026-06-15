from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
from shkandal_database.jobs import ArticleJobStore, ClaimedJob
from shkandal_database.models import Case
from worker_ml.cases.copy import lifecycle_sample
from worker_ml.cases.publication import case_vector_payload
from worker_ml.cases.resolution import (
    _enqueue_resolution_followups,
    _normalize_invalid_case_relations,
    _relation_endpoint,
)
from worker_ml.llm.contracts import CaseResolutionOutput


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
