"""Qdrant client factory."""

from qdrant_client import AsyncQdrantClient

from shkandal_vector_store.config import VectorStoreConfig


def create_qdrant_client(config: VectorStoreConfig) -> AsyncQdrantClient:
    """Create an async Qdrant client from vector-store settings."""

    return AsyncQdrantClient(url=config.qdrant_url)
