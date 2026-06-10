from uuid import UUID, uuid4

from shkandal_database.models import Case
from worker_ml.case_resolution import (
    _case_payload,
    _lifecycle_sample,
    _relation_endpoint,
)


def test_lifecycle_sample_preserves_first_last_and_full_span() -> None:
    cards = [{"position": index} for index in range(100)]

    sample = _lifecycle_sample(cards, 6)

    assert len(sample) == 6
    assert sample[0] == {"position": 0}
    assert sample[-1] == {"position": 99}
    assert [card["position"] for card in sample] == sorted(card["position"] for card in sample)


def test_relation_endpoint_resolves_new_ref_or_existing_uuid() -> None:
    new_case_id = uuid4()
    existing_case_id = uuid4()

    assert _relation_endpoint(None, "new_1", {"new_1": new_case_id}) == new_case_id
    assert _relation_endpoint(str(existing_case_id), None, {}) == existing_case_id


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

    payload = _case_payload(case)

    assert payload.title_uk == "Назва"
    assert payload.article_count == 3
    assert payload.metadata == {"source": "test"}
