from typing import Any

import pytest
from worker_ml.retrieval.embeddings import DOCUMENT_PREFIX, QUERY_PREFIX, E5Embedder


class FakeSentenceEmbeddingModel:
    def __init__(self, vectors: list[list[float]]) -> None:
        self.vectors = vectors
        self.calls: list[dict[str, Any]] = []

    def encode(
        self,
        sentences: list[str],
        *,
        normalize_embeddings: bool,
        convert_to_numpy: bool,
        show_progress_bar: bool,
    ) -> list[list[float]]:
        self.calls.append(
            {
                "sentences": sentences,
                "normalize_embeddings": normalize_embeddings,
                "convert_to_numpy": convert_to_numpy,
                "show_progress_bar": show_progress_bar,
            }
        )
        return self.vectors[: len(sentences)]


def test_embed_query_adds_e5_query_prefix() -> None:
    model = FakeSentenceEmbeddingModel(vectors=[[0.1, 0.2, 0.3]])
    embedder = E5Embedder(model=model, vector_size=3)

    vector = embedder.embed_query("  справа НАБУ  ")

    assert vector == [0.1, 0.2, 0.3]
    assert model.calls == [
        {
            "sentences": [f"{QUERY_PREFIX}справа НАБУ"],
            "normalize_embeddings": True,
            "convert_to_numpy": True,
            "show_progress_bar": False,
        }
    ]


def test_embed_document_adds_e5_passage_prefix() -> None:
    model = FakeSentenceEmbeddingModel(vectors=[[1, 2]])
    embedder = E5Embedder(model=model, vector_size=2)

    vector = embedder.embed_document(" картка справи ")

    assert vector == [1.0, 2.0]
    assert model.calls[0]["sentences"] == [f"{DOCUMENT_PREFIX}картка справи"]


def test_embed_queries_allows_empty_batch() -> None:
    model = FakeSentenceEmbeddingModel(vectors=[])
    embedder = E5Embedder(model=model, vector_size=3)

    assert embedder.embed_queries([]) == []
    assert model.calls == []


def test_embedder_rejects_empty_text() -> None:
    model = FakeSentenceEmbeddingModel(vectors=[])
    embedder = E5Embedder(model=model, vector_size=3)

    with pytest.raises(ValueError, match="must not be empty"):
        embedder.embed_query(" ")


def test_embedder_validates_vector_size() -> None:
    model = FakeSentenceEmbeddingModel(vectors=[[0.1, 0.2]])
    embedder = E5Embedder(model=model, vector_size=3)

    with pytest.raises(ValueError, match="expected 3"):
        embedder.embed_document("текст")
