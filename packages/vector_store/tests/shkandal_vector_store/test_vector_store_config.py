from pathlib import Path

from shkandal_vector_store.config import VectorStoreConfig


def test_vector_store_config_defaults() -> None:
    settings = VectorStoreConfig()

    assert settings.qdrant_url == "http://qdrant:6333"
    assert settings.vector_size == 1536
    assert settings.distance == "cosine"
    assert settings.case_collection_name == "case_cards"
    assert settings.entity_collection_name == "entity_cards"
    assert settings.event_collection_name == "event_cards"


def test_vector_store_config_loads_yaml_overrides(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "config.yaml").write_text(
        "\n".join(
            [
                "qdrant_url: http://localhost:6333",
                "vector_size: 384",
                "distance: dot",
                "case_collection_name: cases_v1",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    settings = VectorStoreConfig()

    assert settings.qdrant_url == "http://localhost:6333"
    assert settings.vector_size == 384
    assert settings.distance == "dot"
    assert settings.case_collection_name == "cases_v1"
