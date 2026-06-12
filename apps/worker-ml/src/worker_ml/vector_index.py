"""Worker-level embedding integration with Qdrant repositories."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import UUID

from qdrant_client import AsyncQdrantClient
from shkandal_vector_store.config import VectorStoreConfig
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
    EventVectorRecord,
    VectorSearchResult,
)

from worker_ml.embeddings import E5Embedder


def create_vector_index_service(
    *,
    embedder: E5Embedder,
    client: AsyncQdrantClient,
    config: VectorStoreConfig,
) -> VectorIndexService:
    """Create a vector-index service from shared Qdrant settings."""

    return VectorIndexService(
        embedder=embedder,
        case_repository=CaseVectorRepository(
            client,
            collection_name=config.case_collection_name,
        ),
        entity_repository=EntityVectorRepository(
            client,
            collection_name=config.entity_collection_name,
        ),
        event_repository=EventVectorRepository(
            client,
            collection_name=config.event_collection_name,
        ),
    )


@dataclass(frozen=True)
class VectorIndexService:
    """Embed cards and query typed vector-store repositories."""

    embedder: E5Embedder
    case_repository: CaseVectorRepository
    entity_repository: EntityVectorRepository
    event_repository: EventVectorRepository

    async def upsert_case(self, point_id: UUID, payload: CaseVectorPayload) -> None:
        """Embed and upsert one case-card vector."""

        await self.case_repository.upsert(
            CaseVectorRecord(
                id=point_id,
                vector=self.embedder.embed_document(_case_text(payload)),
                payload=payload,
            )
        )

    async def upsert_entity(self, point_id: UUID, payload: EntityVectorPayload) -> None:
        """Embed and upsert one entity-card vector."""

        await self.entity_repository.upsert(
            EntityVectorRecord(
                id=point_id,
                vector=self.embedder.embed_document(_entity_text(payload)),
                payload=payload,
            )
        )

    async def upsert_event(self, point_id: UUID, payload: EventVectorPayload) -> None:
        """Embed and upsert one event-card vector."""

        await self.event_repository.upsert(
            EventVectorRecord(
                id=point_id,
                vector=self.embedder.embed_document(_event_text(payload)),
                payload=payload,
            )
        )

    async def search_cases(
        self,
        query_text: str,
        *,
        limit: int,
        score_threshold: float | None = None,
    ) -> list[VectorSearchResult[CaseVectorPayload]]:
        """Embed query text and search case-card vectors."""

        return await self.case_repository.search(
            self.embedder.embed_query(query_text),
            limit=limit,
            score_threshold=score_threshold,
        )

    async def search_entities(
        self,
        query_text: str,
        *,
        limit: int,
        score_threshold: float | None = None,
    ) -> list[VectorSearchResult[EntityVectorPayload]]:
        """Embed query text and search entity-card vectors."""

        return await self.entity_repository.search(
            self.embedder.embed_query(query_text),
            limit=limit,
            score_threshold=score_threshold,
        )

    async def search_entities_batch(
        self,
        query_texts: list[str],
        *,
        limit: int,
    ) -> list[list[VectorSearchResult[EntityVectorPayload]]]:
        """Embed entity queries in one batch and search them concurrently."""

        vectors = self.embedder.embed_queries(query_texts)
        return list(
            await asyncio.gather(
                *(self.entity_repository.search(vector, limit=limit) for vector in vectors)
            )
        )

    async def search_events(
        self,
        query_text: str,
        *,
        limit: int,
        score_threshold: float | None = None,
    ) -> list[VectorSearchResult[EventVectorPayload]]:
        """Embed query text and search event-card vectors."""

        return await self.event_repository.search(
            self.embedder.embed_query(query_text),
            limit=limit,
            score_threshold=score_threshold,
        )

    async def search_events_batch(
        self,
        query_texts: list[str],
        *,
        limit: int,
    ) -> list[list[VectorSearchResult[EventVectorPayload]]]:
        """Embed event queries in one batch and search them concurrently."""

        vectors = self.embedder.embed_queries(query_texts)
        return list(
            await asyncio.gather(
                *(self.event_repository.search(vector, limit=limit) for vector in vectors)
            )
        )


def _case_text(payload: CaseVectorPayload) -> str:
    return _join_text_parts(
        [
            payload.title_uk,
            payload.summary_uk,
            payload.status,
        ]
    )


def _entity_text(payload: EntityVectorPayload) -> str:
    return _join_text_parts(
        [
            payload.canonical_name_uk,
            payload.entity_type,
            *payload.aliases,
            payload.description_uk,
        ]
    )


def _event_text(payload: EventVectorPayload) -> str:
    return _join_text_parts(
        [
            payload.title_uk,
            payload.description_uk,
            _event_date_text(payload),
            payload.location_uk,
        ]
    )


def _join_text_parts(parts: list[str | None]) -> str:
    return "\n".join(part.strip() for part in parts if part and part.strip())


def _event_date_text(payload: EventVectorPayload) -> str | None:
    if payload.event_year is None:
        return None
    parts = [str(payload.event_year)]
    if payload.event_month is not None:
        parts.append(f"{payload.event_month:02d}")
    if payload.event_day is not None:
        parts.append(f"{payload.event_day:02d}")
    return "-".join(parts)
