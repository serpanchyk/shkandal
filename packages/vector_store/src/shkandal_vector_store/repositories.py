"""Thin typed repositories over Qdrant collections."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models

from shkandal_vector_store.schemas import (
    CaseVectorPayload,
    CaseVectorRecord,
    EntityVectorPayload,
    EntityVectorRecord,
    EventVectorPayload,
    EventVectorRecord,
    VectorRecord,
    VectorSearchResult,
)


class BaseVectorRepository[PayloadT: BaseModel, RecordT: VectorRecord[Any]]:
    """Common Qdrant operations for one typed collection."""

    def __init__(
        self,
        client: AsyncQdrantClient,
        collection_name: str,
        payload_model: type[PayloadT],
    ) -> None:
        self.client = client
        self.collection_name = collection_name
        self.payload_model = payload_model

    async def upsert(self, record: RecordT) -> None:
        """Upsert one vector point."""

        await self.client.upsert(
            collection_name=self.collection_name,
            points=[
                models.PointStruct(
                    id=str(record.id),
                    vector=record.vector,
                    payload=record.payload.model_dump(mode="json"),
                )
            ],
        )

    async def delete(self, point_id: UUID) -> None:
        """Delete one vector point by ID."""

        await self.client.delete(
            collection_name=self.collection_name,
            points_selector=models.PointIdsList(points=[str(point_id)]),
        )

    async def search(
        self,
        vector: Sequence[float],
        *,
        limit: int,
        score_threshold: float | None = None,
    ) -> list[VectorSearchResult[PayloadT]]:
        """Search for nearest candidate points."""

        response = await self.client.query_points(
            collection_name=self.collection_name,
            query=list(vector),
            limit=limit,
            score_threshold=score_threshold,
            with_payload=True,
        )

        candidates: list[VectorSearchResult[PayloadT]] = []
        for result in response.points:
            if result.payload is None:
                continue
            candidates.append(
                VectorSearchResult(
                    id=UUID(str(result.id)),
                    score=float(result.score),
                    payload=self.payload_model.model_validate(result.payload),
                )
            )
        return candidates


class CaseVectorRepository(BaseVectorRepository[CaseVectorPayload, CaseVectorRecord]):
    """Qdrant repository for case-card vectors."""

    def __init__(self, client: AsyncQdrantClient, collection_name: str = "case_cards") -> None:
        super().__init__(client, collection_name, CaseVectorPayload)


class EntityVectorRepository(BaseVectorRepository[EntityVectorPayload, EntityVectorRecord]):
    """Qdrant repository for entity-card vectors."""

    def __init__(self, client: AsyncQdrantClient, collection_name: str = "entity_cards") -> None:
        super().__init__(client, collection_name, EntityVectorPayload)


class EventVectorRepository(BaseVectorRepository[EventVectorPayload, EventVectorRecord]):
    """Qdrant repository for event-card vectors."""

    def __init__(self, client: AsyncQdrantClient, collection_name: str = "event_cards") -> None:
        super().__init__(client, collection_name, EventVectorPayload)
