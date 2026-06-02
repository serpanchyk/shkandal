# Shkandal Agent Guide

## Purpose

Shkandal turns scattered Ukrainian media and institutional articles about public
scandals, corruption investigations, political cases, and socially important
stories into Ukrainian-language reader-facing dossiers.

Input:

* Ukrainian media and institutional URLs/articles
* extracted article text, metadata, authors, dates, and remote image URLs
* relevance and retrieval signals from ML workers

Output:

* reader-facing Ukrainian case dossiers
* case timelines and article cards
* linked entities, people, institutions, and related cases
* searchable public case feed and case pages

Core pipeline:
`worker-ingestion -> postgres -> worker-ml -> qdrant -> backend -> frontend`

---

## Agent Discipline

Bias toward correctness over speed.

* Think before coding: state assumptions, blockers, and verification criteria before making ambiguous changes.
* Simplicity first: implement the smallest useful change; avoid speculative features, abstractions, configurability, or dependencies.
* Surgical changes: touch only necessary files; match existing style; do not refactor or reformat adjacent code unless required.
* Goal-driven execution: convert tasks into verifiable goals; for multi-step work, plan `step -> check`; continue until checks pass or a blocker is clear.
* Every changed line must trace to the user request, a failing test, or required verification.
* Do not hide uncertainty, failed checks, skipped checks, assumptions, or unverified behavior.
* Preserve product intent: cases are reader-facing dossiers, not exclusive article clusters.

---

## Service Boundaries

* `apps/backend`: public API and application business boundary.
* `apps/worker-ingestion`: URL discovery, fetching, extraction, article normalization, and remote image URL extraction.
* `apps/worker-ml`: binary relevance classification, article cards, embeddings, Qdrant retrieval, LLM resolution, and deduplication.
* `apps/frontend`: public case feed, case pages, and entity pages.
* `packages/common`: shared runtime utilities only.
* `infra/postgres`: source-of-truth database runtime.
* `infra/qdrant`: rebuildable vector index runtime.

Architecture rules:

* Keep Python code under each workspace member's `src/` tree.
* Keep frontend code inside `apps/frontend`.
* Do not put business logic outside application packages.
* Do not create circular imports between services/packages.
* Understand the target service responsibility before changing code.
* `postgres` is the source of truth; `qdrant` is a rebuildable retrieval index.
* Do not introduce Redis, queues, or new databases unless the product need is documented first.

---

## Coding Rules

Use:

* strict typing and explicit data contracts
* async-first I/O for network, database, crawling, and LLM calls
* structured JSON logging through `shkandal_common.logging`
* Pydantic settings classes for runtime configuration
* minimal dependencies
* production-ready code only
* Docker Compose for normal project runs unless a direct per-service local run is explicitly requested or clearly necessary

Never:

* use `print()` for runtime logging
* use `pip install`; use the project `uv` workflow
* commit real `.env` files, secrets, tokens, cookies, or API keys
* add unnecessary dependencies
* weaken typing, linting, tests, or validation to make checks pass
* use or switch Docker contexts
* silently change public content language rules

Content/product rules:

* Keep public generated content Ukrainian-only.
* Keep code, schema names, API fields, and internal identifiers English.
* Treat raw articles as evidence, not as final reader-facing copy.
* Keep article clusters, cases, entities, and dossiers conceptually separate.
* New behavior must stay debuggable through logs, traces, tests, or clear errors.

---

## Verification

Every feature needs deterministic verification.

Prefer:

* bug fix -> reproduce with a failing test, then fix
* feature -> test expected behavior and edge cases
* refactor -> tests pass before and after
* ML/retrieval behavior -> include a small deterministic fixture or documented evaluation command

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

If a check cannot be run, report why, what was skipped, and what remains unverified.

---

## Docs Rules

Update `PROJECT_CONTEXT.md`, `README.md`, and relevant files under `docs/system/`
when service boundaries, runtime dependencies, configuration, data flow, or
implemented behavior changes.

Also:

* update task/problem docs when the work changes them
* for significant product or architecture changes, add a note to the relevant vision/context document if one exists
* for significant ideas, create or update a focused system doc under `docs/system/`
* before documenting a problem, check `docs/problems/` for an existing related doc
* keep docs concise and aligned with implemented behavior

Do not document imaginary architecture. Docs must describe what exists or what is
explicitly accepted as a plan.

---

## Runtime Rules

When starting the project:

* prefer Docker Compose
* use direct service runs only when explicitly requested or clearly necessary
* switch docker contexts, if needed

When debugging:

* check log tails first
* preserve useful logs and error traces
* avoid destructive cleanup unless needed
* before clean reset, volume deletion, or container cleanup, state what will be removed

---

## Git and PR Rules

After code or doc changes:

* run relevant checks when possible
* commit at the end unless the user explicitly says not to
* do not commit broken or unverified work without saying so clearly

When the user asks for a PR:

* write a clear PR description
* include summary, tests/checks, docs updates, and known limitations
* create or open the PR only if explicitly asked and tooling is available
* check the CI workflow and resolve problems if they appear

GitHub MCP:

* You need access to check, edit or create issues, when needed.
* You need to answer reviews of PR.

---

## Completion Report

End each task with:

* what changed
* tests/checks run
* docs updated or not needed
* remaining risks or blockers

---

## Previous Project

This is the second try at creating Shkandal, so the previous version can be used
for ideas, migration references, and implementation lessons:

1. ML version: https://github.com/loxar-ua/case-monitoring-etl
2. Backend + frontend: https://github.com/loxar-ua/case-monitoring-web
