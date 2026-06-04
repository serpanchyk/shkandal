from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from shkandal_vector_store.schemas import (
    CaseVectorPayload,
    EntityVectorPayload,
    EventVectorPayload,
)
from worker_ml.vector_index import VectorIndexService


class FakeEmbedder:
    def __init__(self) -> None:
        self.queries: list[str] = []
        self.documents: list[str] = []

    def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return [0.1, 0.2]

    def embed_document(self, text: str) -> list[float]:
        self.documents.append(text)
        return [0.3, 0.4]


class FakeRepository:
    def __init__(self) -> None:
        self.upserts: list[Any] = []
        self.searches: list[dict[str, Any]] = []

    async def upsert(self, record: Any) -> None:
        self.upserts.append(record)

    async def search(
        self,
        vector: list[float],
        *,
        limit: int,
        score_threshold: float | None = None,
    ) -> list[Any]:
        self.searches.append(
            {
                "vector": vector,
                "limit": limit,
                "score_threshold": score_threshold,
            }
        )
        return []


ServiceParts = tuple[
    VectorIndexService,
    FakeEmbedder,
    FakeRepository,
    FakeRepository,
    FakeRepository,
]


def _service() -> ServiceParts:
    embedder = FakeEmbedder()
    case_repository = FakeRepository()
    entity_repository = FakeRepository()
    event_repository = FakeRepository()
    return (
        VectorIndexService(
            embedder=embedder,  # type: ignore[arg-type]
            case_repository=case_repository,  # type: ignore[arg-type]
            entity_repository=entity_repository,  # type: ignore[arg-type]
            event_repository=event_repository,  # type: ignore[arg-type]
        ),
        embedder,
        case_repository,
        entity_repository,
        event_repository,
    )


async def test_upsert_case_embeds_card_text_and_preserves_payload() -> None:
    service, embedder, case_repository, _entity_repository, _event_repository = _service()
    point_id = uuid4()
    payload = CaseVectorPayload(
        slug="case-a",
        title_uk="Назва справи",
        summary_uk="Опис справи",
        status="active",
    )

    await service.upsert_case(point_id, payload)

    assert embedder.documents == ["Назва справи\nОпис справи\nactive"]
    record = case_repository.upserts[0]
    assert record.id == point_id
    assert record.vector == [0.3, 0.4]
    assert record.payload == payload


async def test_upsert_entity_includes_aliases() -> None:
    service, embedder, _case_repository, entity_repository, _event_repository = _service()
    point_id = uuid4()
    payload = EntityVectorPayload(
        slug="entity-a",
        entity_type="person",
        canonical_name_uk="Ім'я",
        aliases=["Псевдонім"],
        description_uk="Опис",
    )

    await service.upsert_entity(point_id, payload)

    assert embedder.documents == ["Ім'я\nperson\nПсевдонім\nОпис"]
    assert entity_repository.upserts[0].payload == payload


async def test_search_events_embeds_query_and_passes_threshold() -> None:
    service, embedder, _case_repository, _entity_repository, event_repository = _service()

    results = await service.search_events("подія", limit=5, score_threshold=0.8)

    assert results == []
    assert embedder.queries == ["подія"]
    assert event_repository.searches == [{"vector": [0.1, 0.2], "limit": 5, "score_threshold": 0.8}]


async def test_upsert_event_includes_date_and_location() -> None:
    service, embedder, _case_repository, _entity_repository, event_repository = _service()
    point_id = UUID("00000000-0000-0000-0000-000000000001")
    payload = EventVectorPayload(
        slug="event-a",
        title_uk="Подія",
        description_uk=None,
        event_date=None,
        location_uk="Київ",
    )

    await service.upsert_event(point_id, payload)

    assert embedder.documents == ["Подія\nКиїв"]
    assert event_repository.upserts[0].id == point_id
