import pytest
from qdrant_client.http import models
from shkandal_vector_store.bootstrap import bootstrap_qdrant_collections
from shkandal_vector_store.config import VectorStoreConfig


class FakeBootstrapClient:
    def __init__(self, existing_collections: set[str] | None = None) -> None:
        self.existing_collections = existing_collections or set()
        self.created: list[tuple[str, models.VectorParams]] = []

    async def collection_exists(self, collection_name: str) -> bool:
        return collection_name in self.existing_collections

    async def create_collection(
        self,
        *,
        collection_name: str,
        vectors_config: models.VectorParams,
    ) -> None:
        self.created.append((collection_name, vectors_config))
        self.existing_collections.add(collection_name)


async def test_bootstrap_creates_missing_collections() -> None:
    client = FakeBootstrapClient()
    config = VectorStoreConfig(vector_size=384, distance="dot")

    await bootstrap_qdrant_collections(client, config)  # type: ignore[arg-type]

    assert [name for name, _params in client.created] == [
        "case_cards",
        "entity_cards",
        "event_cards",
    ]
    assert all(params.size == 384 for _name, params in client.created)
    assert all(params.distance == models.Distance.DOT for _name, params in client.created)


async def test_bootstrap_skips_existing_collections() -> None:
    client = FakeBootstrapClient(existing_collections={"case_cards"})

    await bootstrap_qdrant_collections(client, VectorStoreConfig())  # type: ignore[arg-type]

    assert [name for name, _params in client.created] == ["entity_cards", "event_cards"]


async def test_bootstrap_rejects_unknown_distance() -> None:
    client = FakeBootstrapClient()

    with pytest.raises(ValueError, match="Unsupported Qdrant distance"):
        await bootstrap_qdrant_collections(
            client,  # type: ignore[arg-type]
            VectorStoreConfig(distance="unknown"),
        )
