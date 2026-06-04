FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1
ENV UV_PROJECT_ENVIRONMENT=/opt/venv

COPY pyproject.toml uv.lock ./
COPY packages/common/pyproject.toml ./packages/common/pyproject.toml
COPY packages/common/src ./packages/common/src
COPY packages/database/pyproject.toml ./packages/database/pyproject.toml
COPY packages/database/src ./packages/database/src
COPY apps/worker-ml/pyproject.toml ./apps/worker-ml/pyproject.toml
COPY apps/worker-ml/src ./apps/worker-ml/src

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package shkandal-worker-ml

FROM python:3.12-slim-bookworm

WORKDIR /app

COPY --from=builder /opt/venv /app/.venv
COPY apps/worker-ml/src ./src
COPY apps/worker-ml/config.yaml ./config.yaml
COPY artifacts/models ./artifacts/models

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"

CMD ["python", "-m", "worker_ml.main"]
