from datetime import date
from typing import Any
from uuid import UUID, uuid4

from qdrant_client.http import models
from shkandal_vector_store.repositories import (
    CaseVectorRepository,
    EntityVectorRepository,
    EventVectorRepository,
)
from shkandal_vector_store.schemas import (
    CaseVectorPayload,
    CaseVectorRecord,
    EntityVectorPayload,
    EntityVectorRecord,
    EventVectorPayload,
)


class FakeScoredPoint:
    def __init__(self, *, point_id: UUID, score: float, payload: dict[str, Any] | None) -> None:
        self.id = str(point_id)
        self.score = score
        self.payload = payload


class FakeRepositoryClient:
    def __init__(self) -> None:
        self.upserts: list[dict[str, Any]] = []
        self.deletes: list[dict[str, Any]] = []
        self.searches: list[dict[str, Any]] = []
        self.search_results: list[FakeScoredPoint] = []

    async def upsert(
        self,
        *,
        collection_name: str,
        points: list[models.PointStruct],
    ) -> None:
        self.upserts.append({"collection_name": collection_name, "points": points})

    async def delete(
        self,
        *,
        collection_name: str,
        points_selector: models.PointIdsList,
    ) -> None:
        self.deletes.append(
            {"collection_name": collection_name, "points_selector": points_selector}
        )

    async def query_points(
        self,
        *,
        collection_name: str,
        query: list[float],
        limit: int,
        score_threshold: float | None,
        with_payload: bool,
    ) -> Any:
        self.searches.append(
            {
                "collection_name": collection_name,
                "query_vector": query,
                "limit": limit,
                "score_threshold": score_threshold,
                "with_payload": with_payload,
            }
        )
        return type("FakeQueryResponse", (), {"points": self.search_results})()


async def test_case_repository_upserts_typed_payload() -> None:
    client = FakeRepositoryClient()
    repository = CaseVectorRepository(client, collection_name="cases_v1")  # type: ignore[arg-type]
    point_id = uuid4()

    await repository.upsert(
        CaseVectorRecord(
            id=point_id,
            vector=[0.1, 0.2],
            payload=CaseVectorPayload(
                slug="case-a",
                title_uk="Тестова справа",
                summary_uk="Короткий опис",
                status="active",
                article_count=2,
                event_count=1,
                metadata={"source": "test"},
            ),
        )
    )

    assert client.upserts[0]["collection_name"] == "cases_v1"
    point = client.upserts[0]["points"][0]
    assert point.id == str(point_id)
    assert point.vector == [0.1, 0.2]
    assert point.payload == {
        "slug": "case-a",
        "title_uk": "Тестова справа",
        "summary_uk": "Короткий опис",
        "status": "active",
        "article_count": 2,
        "event_count": 1,
        "metadata": {"source": "test"},
    }


async def test_entity_repository_delete_uses_point_id_selector() -> None:
    client = FakeRepositoryClient()
    repository = EntityVectorRepository(client)  # type: ignore[arg-type]
    point_id = uuid4()

    await repository.delete(point_id)

    assert client.deletes[0]["collection_name"] == "entity_cards"
    selector = client.deletes[0]["points_selector"]
    assert selector.points == [str(point_id)]


async def test_event_repository_search_maps_payloads() -> None:
    client = FakeRepositoryClient()
    repository = EventVectorRepository(client)  # type: ignore[arg-type]
    event_id = uuid4()
    client.search_results = [
        FakeScoredPoint(
            point_id=event_id,
            score=0.91,
            payload={
                "slug": "event-a",
                "title_uk": "Подія",
                "description_uk": "Опис",
                "event_date": "2026-06-04",
                "event_date_precision": "day",
                "location_uk": "Київ",
                "metadata": {},
            },
        ),
        FakeScoredPoint(point_id=uuid4(), score=0.5, payload=None),
    ]

    results = await repository.search([0.3, 0.4], limit=3, score_threshold=0.8)

    assert client.searches == [
        {
            "collection_name": "event_cards",
            "query_vector": [0.3, 0.4],
            "limit": 3,
            "score_threshold": 0.8,
            "with_payload": True,
        }
    ]
    assert len(results) == 1
    assert results[0].id == event_id
    assert results[0].score == 0.91
    assert results[0].payload == EventVectorPayload(
        slug="event-a",
        title_uk="Подія",
        description_uk="Опис",
        event_date=date(2026, 6, 4),
        event_date_precision="day",
        location_uk="Київ",
    )


async def test_entity_repository_upsert_serializes_aliases() -> None:
    client = FakeRepositoryClient()
    repository = EntityVectorRepository(client, collection_name="entities_v1")  # type: ignore[arg-type]
    point_id = uuid4()

    await repository.upsert(
        EntityVectorRecord(
            id=point_id,
            vector=[0.5],
            payload=EntityVectorPayload(
                slug="entity-a",
                entity_type="person",
                canonical_name_uk="Ім'я",
                aliases=["І. Прізвище"],
                description_uk=None,
            ),
        )
    )

    point = client.upserts[0]["points"][0]
    assert client.upserts[0]["collection_name"] == "entities_v1"
    assert point.payload["aliases"] == ["І. Прізвище"]
