# Worker ML

The ML worker will own relevance filtering, article card enrichment, embeddings,
candidate case retrieval, LLM-based resolution, and deduplication workflows.

Current implementation is a runnable async process shell with configuration and
structured startup logging.
