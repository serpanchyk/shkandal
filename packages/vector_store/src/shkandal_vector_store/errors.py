"""Shared vector-store exception types."""


class VectorStoreError(RuntimeError):
    """Base error for vector-store operations."""


class VectorStoreUnavailableError(VectorStoreError):
    """Raised when Qdrant cannot be reached for a transient transport reason."""
