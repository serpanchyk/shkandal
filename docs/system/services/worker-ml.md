# Worker ML

The ML worker owns the semantic processing pipeline after article extraction.

Planned responsibilities:

- poll PostgreSQL for articles missing ML-derived state and enqueue idempotent
  jobs for downstream processing;
- create one `classify_article` job for each article missing
  `article_relevance`;
- run the local binary relevance classifier before any LLM calls;
- store classifier decision, score, classifier name, and classifier version;
- use a configured classifier threshold, chosen from a threshold sweep that
  favors recall for relevance candidates while keeping LLM volume tolerable;
- preserve negative classifier decisions for future contextual reprocessing
  when a known case/entity match or newer classifier version justifies revisiting
  skipped articles;
- create provisional Ukrainian article cards with Pydantic-validated LLM JSON;
- embed article, case, entity, and event cards;
- query Qdrant case, entity, and event collections;
- resolve article-case relationships and explicit case relations;
- resolve global entities from provisional article entities;
- resolve global strict real-world events from provisional article events;
- assign resolved entities/events only to relevant linked cases;
- materialize direct `case_entities` and `case_events` links;
- record LLM run metadata, prompt name/version, model, status, raw output, and repair attempts.

LLM prompts live as Ukrainian plain-text files in this service. LangChain loads
those files inside each LLM task for prompt handling and simple chains, but it
does not own worker orchestration, retries, persistence, or database mutation.
Invalid JSON output is repaired once with a schema-only repair prompt, then
marked failed if still invalid.

All runtime LLM traffic goes through the LiteLLM proxy. `worker-ml` requests
logical model aliases (`shkandal-article-card`, `shkandal-case-resolution`,
`shkandal-entity-resolution`, `shkandal-event-resolution`, and
`shkandal-repair`) through the proxy's OpenAI-compatible endpoint. Provider
routing, provider credentials, throttling, and fallback policy belong to the
proxy configuration, not to `worker-ml`.

When the proxy or provider returns HTTP `429`, the worker persists a shared LLM
cooldown, defers the rejected job without consuming a job attempt, and ends the
current pass. Later scheduled passes exit before model loading or job claiming
until the cooldown expires. The worker honors usable `Retry-After` values. A
first ambiguous `429` creates a five-minute cooldown; a second within 15
minutes infers a one-hour cooldown. Other API errors and invalid output remain
per-job failures, and each LLM request has a five-minute timeout.

The current implementation supports a systemd-scheduled bounded pass that
creates idempotent `classify_article` jobs for articles missing
`article_relevance` and processes one configured batch. Relevant classifier
results enqueue `create_article_card`; the worker sends compact article evidence
through the `article_card` prompt, validates `ArticleCardOutput`, and stores the
result in `article_cards` with `llm_runs` provenance. Article text sent to the
LLM is capped at 20,000 characters. The table stores an indexed
`is_case_candidate` column so later resolution stages can select only trackable
cases; the gate is omitted from `card_json` to avoid duplicating it. An explicit
continuous polling mode remains available for direct use. It also includes an
embedding service and vector-index integration for future card resolution jobs.

The article-card prompt considers only the main article and excludes related
articles, recommendations, boilerplate, and unrelated background. Its contract
separates classifier relevance from stricter case candidacy. Case candidates
have a main event, one to three events, up to eight central entities, and up to
eight case-signature terms. Non-case cards retain only the cleaned title,
summary, and a fixed noise reason; their events, entities, and signature terms
are empty.

Future case, entity, and event resolution handlers must load cards through the
case-candidate gate. A stored non-case card remains available for inspection but
must not create provisional cases, events, or entities downstream.

After an article-card prompt or contract change, inspect and explicitly apply a
full regeneration. Apply mode refuses to run while any article-card job is
running, deletes current cards, and resets or creates card jobs for all
classifier-positive articles while preserving historical `llm_runs`:

```bash
uv run python -m worker_ml.reprocess_article_cards
uv run python -m worker_ml.reprocess_article_cards --apply
```

To compare a small stable sample after a prompt change, regenerate only the most
recently created existing cards:

```bash
uv run python -m worker_ml.reprocess_article_cards --apply --limit 10
docker compose --profile jobs run --rm -e CLAIM_BATCH_SIZE=10 worker-ml
```

Run the default local one-shot pass or optional direct loop mode:

```bash
docker compose --profile jobs run --rm worker-ml
python -m worker_ml.main --loop
```

On servers, `shkandal-ml-worker.timer` starts a one-shot pass five minutes after
the previous pass becomes inactive. `worker-ml` continues to depend on the Compose `llm-proxy` because
article-card and resolution stages use its logical model aliases.

Local model artifacts live under `artifacts/models/` in the repository working
tree. Binary artifacts are ignored by Git and tracked by DVC; small manifests
and `.dvc` pointer files are committed for metadata and reproducibility. The
first relevance artifact path is
`artifacts/models/relevance/tfidf_logistic_noise_assigned/`.

The current relevance model binary is tracked by
`artifacts/models/relevance/tfidf_logistic_noise_assigned/tfidf_logistic_noise_assigned.joblib.dvc`.
A shared DVC remote has not been configured yet, so `dvc push`/`dvc pull`
require adding a deployment-specific remote first.

The first embedding artifact path is
`artifacts/models/embeddings/multilingual_e5_small/`. It uses
`intfloat/multilingual-e5-small` through Sentence Transformers. The checked-in
manifest records the Hugging Face revision, local model path, 384-dimensional
output size, normalized embeddings, and E5 prefix policy.

The worker embedding service prefixes retrieval queries with `query: ` and
stored card/document text with `passage: ` before encoding. It validates
non-empty text and the configured vector size. `VectorIndexService` composes
that embedder with the shared Qdrant case, entity, and event repositories for
typed upsert and search operations. Article-card generation and resolution jobs
are separate pipeline stages; only article-card generation is implemented.

The relevance classifier loads `manifest.json` and the sibling joblib pipeline
from the configured `relevance_model_dir`. The current artifact was produced
with scikit-learn `1.8.0`, so `worker-ml` pins that runtime version to avoid
unsafe pickle-version drift.

The worker should load and validate the configured relevance model eagerly at
startup before consuming jobs. Missing artifacts, manifest mismatches, or missing
positive-class score support are startup errors.

`article_relevance.is_relevant=true` means the classifier accepted the article
as a relevance candidate for downstream resolution. It does not mean the article
is public dossier evidence. Public evidence is created by `case_articles` links
with source provenance.

At the product boundary, classifier labels are `relevant` and `irrelevant`, and
the stored score is the positive-class relevance score. Early model artifacts may
still record historical research labels such as `assigned` and `noise`; the
worker must map those labels explicitly instead of treating the artifact labels
as product language.

The current handler maps `assigned` to positive relevance probability and
`noise` to negative relevance. Classifier input is the article title, two
newlines, then extracted text, matching the training notebook. Articles missing
extracted text are stored as irrelevant with score `0` and metadata explaining
the missing text.

Below-threshold articles normally skip LLM work in the MVP, but they remain
stored with score, classifier metadata, threshold metadata, extracted text, and
source data so they can be revisited later.

The worker should use the shared PostgreSQL job store for article-scoped jobs.
Jobs are unique by `(job_type, article_id)` for the lifetime of the row. Workers
claim jobs with `FOR UPDATE SKIP LOCKED`, treat `running` rows as reclaimable
leases after the configured stale-job timeout, and count each claim as an
attempt.
