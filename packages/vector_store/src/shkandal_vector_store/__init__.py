"""Qdrant vector-store primitives for Shkandal services."""

from shkandal_vector_store.bootstrap import bootstrap_qdrant_collections
from shkandal_vector_store.client import create_qdrant_client
from shkandal_vector_store.config import VectorStoreConfig
from shkandal_vector_store.errors import VectorStoreError, VectorStoreUnavailableError
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

__all__ = [
    "CaseVectorPayload",
    "CaseVectorRecord",
    "CaseVectorRepository",
    "EntityVectorPayload",
    "EntityVectorRecord",
    "EntityVectorRepository",
    "EventVectorPayload",
    "EventVectorRecord",
    "EventVectorRepository",
    "VectorSearchResult",
    "VectorStoreConfig",
    "VectorStoreError",
    "VectorStoreUnavailableError",
    "bootstrap_qdrant_collections",
    "create_qdrant_client",
]
