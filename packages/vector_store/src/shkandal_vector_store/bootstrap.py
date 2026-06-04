"""Qdrant collection bootstrap helpers."""

import logging

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models

from shkandal_vector_store.config import VectorStoreConfig

logger = logging.getLogger(__name__)


def _qdrant_distance(distance: str) -> models.Distance:
    normalized = distance.strip().lower()
    for qdrant_distance in models.Distance:
        if normalized in {qdrant_distance.name.lower(), qdrant_distance.value.lower()}:
            return qdrant_distance

    valid_distances = ", ".join(distance.value.lower() for distance in models.Distance)
    msg = f"Unsupported Qdrant distance '{distance}'. Expected one of: {valid_distances}"
    raise ValueError(msg)


async def bootstrap_qdrant_collections(
    client: AsyncQdrantClient,
    config: VectorStoreConfig,
) -> None:
    """Create configured Qdrant collections when they are missing."""

    vector_params = models.VectorParams(
        size=config.vector_size,
        distance=_qdrant_distance(config.distance),
    )
    collection_names = (
        config.case_collection_name,
        config.entity_collection_name,
        config.event_collection_name,
    )

    for collection_name in collection_names:
        exists = await client.collection_exists(collection_name)
        if exists:
            logger.info(
                "qdrant_collection_exists",
                extra={"collection_name": collection_name},
            )
            continue

        await client.create_collection(
            collection_name=collection_name,
            vectors_config=vector_params,
        )
        logger.info(
            "qdrant_collection_created",
            extra={
                "collection_name": collection_name,
                "vector_size": config.vector_size,
                "distance": config.distance,
            },
        )
