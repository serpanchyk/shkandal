"""Vector-store configuration."""

from shkandal_common.config import BaseServiceConfig


class VectorStoreConfig(BaseServiceConfig):
    """Qdrant settings shared by vector-store users."""

    qdrant_url: str = "http://qdrant:6333"
    vector_size: int = 1536
    distance: str = "cosine"
    case_collection_name: str = "case_cards"
    entity_collection_name: str = "entity_cards"
    event_collection_name: str = "event_cards"
