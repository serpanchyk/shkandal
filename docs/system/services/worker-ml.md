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

The current implementation supports a systemd-scheduled bounded pass that
creates idempotent `classify_article` jobs for articles missing
`article_relevance` and processes one configured batch. An explicit continuous
polling mode remains available for direct use. It also includes an embedding
service and vector-index integration for future card resolution jobs.

Run the default local one-shot pass or optional direct loop mode:

```bash
docker compose --profile jobs run --rm worker-ml
python -m worker_ml.main --loop
```

On servers, `shkandal-ml-worker.timer` starts the one-shot container every 10
minutes. `worker-ml` continues to depend on the Compose `llm-proxy` because
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
are still separate future pipeline stages.

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
