"""Sentence embedding services for worker-ml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

QUERY_PREFIX = "query: "
DOCUMENT_PREFIX = "passage: "


class SentenceEmbeddingModel(Protocol):
    """Subset of SentenceTransformer used by the worker."""

    def encode(
        self,
        sentences: list[str],
        *,
        normalize_embeddings: bool,
        convert_to_numpy: bool,
        show_progress_bar: bool,
    ) -> Any:
        """Return embeddings for input sentences."""


@dataclass(frozen=True)
class E5Embedder:
    """Embed text with a multilingual E5 Sentence Transformers model."""

    model: SentenceEmbeddingModel
    vector_size: int = 384
    normalize_embeddings: bool = True

    @classmethod
    def load(cls, model_dir: str | Path, *, vector_size: int = 384) -> E5Embedder:
        """Load the configured Sentence Transformers model artifact."""

        from sentence_transformers import SentenceTransformer

        root = Path(model_dir)
        if not root.exists():
            raise FileNotFoundError(f"embedding model directory does not exist: {root}")

        model = cast(SentenceEmbeddingModel, SentenceTransformer(str(root)))
        return cls(model=model, vector_size=vector_size)

    def embed_query(self, text: str) -> list[float]:
        """Embed one retrieval query."""

        return self.embed_queries([text])[0]

    def embed_document(self, text: str) -> list[float]:
        """Embed one retrieval document."""

        return self.embed_documents([text])[0]

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        """Embed retrieval queries with E5 query prefixes."""

        return self._embed_prefixed(texts, prefix=QUERY_PREFIX)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed retrieval documents with E5 passage prefixes."""

        return self._embed_prefixed(texts, prefix=DOCUMENT_PREFIX)

    def _embed_prefixed(self, texts: list[str], *, prefix: str) -> list[list[float]]:
        if not texts:
            return []

        prefixed_texts = [f"{prefix}{_normalize_text(text)}" for text in texts]
        embeddings = self.model.encode(
            prefixed_texts,
            normalize_embeddings=self.normalize_embeddings,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        vectors = [_vector_to_floats(vector) for vector in embeddings]
        for vector in vectors:
            if len(vector) != self.vector_size:
                raise ValueError(
                    f"embedding vector has size {len(vector)}, expected {self.vector_size}"
                )
        return vectors


def _normalize_text(text: str) -> str:
    normalized = text.strip()
    if not normalized:
        raise ValueError("embedding text must not be empty")
    return normalized


def _vector_to_floats(vector: Any) -> list[float]:
    if hasattr(vector, "tolist"):
        values = vector.tolist()
    else:
        values = vector
    return [float(value) for value in values]
