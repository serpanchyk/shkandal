"""Typed vector-store records and search results."""

from datetime import date
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CaseVectorPayload(BaseModel):
    """Payload stored for a case-card vector."""

    slug: str
    title_uk: str
    summary_uk: str | None = None
    status: str
    article_count: int = 0
    event_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class EntityVectorPayload(BaseModel):
    """Payload stored for an entity-card vector."""

    slug: str
    entity_type: str
    canonical_name_uk: str
    aliases: list[str] = Field(default_factory=list)
    description_uk: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EventVectorPayload(BaseModel):
    """Payload stored for an event-card vector."""

    slug: str
    title_uk: str
    description_uk: str | None = None
    event_date: date | None = None
    event_date_precision: str | None = None
    location_uk: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class VectorRecord[PayloadT: BaseModel](BaseModel):
    """Vector point ready to be stored in Qdrant."""

    id: UUID
    vector: list[float]
    payload: PayloadT

    model_config = ConfigDict(arbitrary_types_allowed=True)


class VectorSearchResult[PayloadT: BaseModel](BaseModel):
    """Typed search candidate returned from Qdrant."""

    id: UUID
    score: float
    payload: PayloadT


CaseVectorRecord = VectorRecord[CaseVectorPayload]
EntityVectorRecord = VectorRecord[EntityVectorPayload]
EventVectorRecord = VectorRecord[EventVectorPayload]
