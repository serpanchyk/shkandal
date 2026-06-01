# Shkandal Agent Guide

## Purpose

Shkandal turns scattered Ukrainian media articles about public scandals,
corruption investigations, political cases, and socially important stories into
structured case files.

## Service Boundaries

- `apps/backend`: public API and application business boundary.
- `apps/worker-ingestion`: URL discovery, fetching, extraction, and article normalization.
- `apps/worker-ml`: relevance classification, embeddings, retrieval, LLM resolution, and deduplication.
- `apps/frontend`: reader and review UI.
- `packages/common`: shared runtime utilities only.
- `infra/postgres`: source-of-truth database runtime.
- `infra/qdrant`: rebuildable vector index runtime.

## Coding Rules

- Keep Python code under each workspace member's `src/` tree.
- Use structured JSON logging through `shkandal_common.logging`.
- Load runtime settings through Pydantic settings classes.
- Do not commit real `.env` files or secrets.
- Do not introduce Redis, queues, or new databases unless the product need is documented first.

## Verification

Run these before reporting completion when dependencies are available:

```bash
uv lock
uv sync --frozen --all-packages
uv run pre-commit run --all-files
uv run pytest
docker compose config
```

For frontend changes, also run:

```bash
npm install
npm run lint
npm run build
```

## Docs

Update `PROJECT_CONTEXT.md` and `docs/system/` when service boundaries,
runtime dependencies, configuration, or implemented behavior changes.
