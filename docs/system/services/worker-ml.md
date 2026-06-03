# Worker ML

The ML worker owns the semantic processing pipeline after article extraction.

Planned responsibilities:

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

LLM prompts should live as Ukrainian plain-text files in this service. Invalid
JSON output is repaired once, then marked failed if still invalid.

The current implementation is a runnable async process shell with configuration
and structured startup logging.

Local model artifacts live under `artifacts/models/` in the repository working
tree. Binary artifacts are ignored by git; small manifests can be committed for
metadata and reproducibility. The first relevance artifact path is
`artifacts/models/relevance/tfidf_logistic_noise_assigned/`.

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

Below-threshold articles normally skip LLM work in the MVP, but they remain
stored with score, classifier metadata, threshold metadata, extracted text, and
source data so they can be revisited later.
