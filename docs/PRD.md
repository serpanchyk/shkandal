# PRD: Automatic Ukrainian Public Dossiers

## Problem Statement

Ukrainian news about public scandals, corruption investigations, political
cases, institutional decisions, and socially important stories is fragmented
across many media and official sources. Readers can see separate articles, but
they lose the larger context: what the case is, who is involved, what happened
in chronological order, and which source articles support each development.

Shkandal needs a first product shape that can automatically turn source
articles into public Ukrainian-language dossiers without requiring a manual
review team.

## Solution

Build an automatic article-to-dossier pipeline. The system discovers and stores
source articles, classifies relevance with a local binary classifier, creates
provisional Ukrainian article cards with LLM JSON contracts, retrieves nearby
cases/entities/events from Qdrant, resolves relationships with the LLM, stores
the durable graph in PostgreSQL, and exposes live public case and entity pages.

Cases are reader-facing dossiers, not exclusive clusters. Articles, events, and
entities can connect to multiple cases. Case pages update immediately from
current database rows.

## User Stories

1. As a Ukrainian reader, I want to see a modern feed of public cases, so that I can understand what important stories are active.
2. As a Ukrainian reader, I want to sort cases by latest updates, so that I can follow newly developing stories.
3. As a Ukrainian reader, I want to sort cases by newest cases, so that I can discover newly created dossiers.
4. As a Ukrainian reader, I want to sort cases by most viewed, so that I can see what other readers are paying attention to.
5. As a Ukrainian reader, I want to sort cases by biggest article count, so that I can find large long-running stories.
6. As a Ukrainian reader, I want to sort cases by recent velocity, so that I can see what is trending now.
7. As a Ukrainian reader, I want each case to have a stable Ukrainian title, so that I can recognize the dossier over time.
8. As a Ukrainian reader, I want each case to have a short neutral Ukrainian summary, so that I can understand the topic quickly.
9. As a Ukrainian reader, I want a chronological event timeline, so that I can follow how the case developed.
10. As a Ukrainian reader, I want each event to show supporting articles, so that I can verify where the claim came from.
11. As a Ukrainian reader, I want article previews to include source, date, title, and image when available, so that source lists are readable.
12. As a Ukrainian reader, I want article preview clicks to open the original source page, so that I can read the full article at the publisher.
13. As a Ukrainian reader, I want people and organizations listed on a case page, so that I can see who is involved.
14. As a Ukrainian reader, I want entity pages, so that I can see related cases and mentioned articles for a person or organization.
15. As a Ukrainian reader, I want a short disclaimer that pages are automatically assembled, so that I understand how to read the output.
16. As a project owner, I want public content generated only in Ukrainian, so that the product stays focused on Ukraine.
17. As a project owner, I want code and database fields in English, so that development remains compatible with tooling and contributors.
18. As a project owner, I want a local classifier to filter relevance before LLM calls, so that limited LLM resources are not wasted on irrelevant articles.
19. As a project owner, I want irrelevant articles stored with negative relevance decisions, so that classifier quality can be evaluated and improved.
20. As a project owner, I want raw HTML stored for all articles, so that extraction can be improved later without re-crawling.
21. As a project owner, I want a curated source list first, so that ingestion quality is controlled before broad crawling.
22. As a project owner, I want a one-year backfill before launch, so that first public pages are not empty or misleadingly thin.
23. As a project owner, I want backfill resolution oldest-to-newest, so that case timelines grow in historical order.
24. As a project owner, I want cases to be reader-facing dossiers rather than exclusive clusters, so that broad and specific cases can overlap.
25. As a project owner, I want explicit case relations, so that broad/specific and related cases can be navigated.
26. As a project owner, I want one relevant article to be enough to create a case, so that the system favors coverage and speed.
27. As a project owner, I want case-linked articles to be allowed without extracted events, so that background articles can still support a dossier.
28. As a project owner, I want one global entity table, so that people, institutions, organizations, and companies can be deduplicated consistently.
29. As a project owner, I want global events shared across cases, so that the same real-world occurrence is not duplicated.
30. As a project owner, I want one supporting article to be enough for an event, so that timelines can update quickly while preserving provenance.
31. As a project owner, I want event identity to be strict, so that timelines do not merge separate developments.
32. As a project owner, I want case-entity and case-event links materialized directly, so that public pages are simple and fast to query.
33. As a project owner, I want article-level provenance retained, so that every public event/entity can be traced back to supporting articles.
34. As a project owner, I want LLM prompts in plain Ukrainian files, so that prompt logic is visible and editable.
35. As a project owner, I want LLM outputs validated by Pydantic JSON schemas, so that invalid model output does not mutate the database.
36. As a project owner, I want invalid LLM output repaired once and then failed, so that errors are recoverable without publishing partial bad data.
37. As a project owner, I want Qdrant collections for cases, entities, and events, so that resolution can retrieve candidates for each identity type.
38. As a project owner, I want PostgreSQL as the source of truth, so that Qdrant can be rebuilt and does not own durable state.
39. As a project owner, I want one generic jobs table, so that background work can start without Redis.
40. As a project owner, I want anonymous aggregate case view counters, so that popular sorting works without user tracking.
41. As a project owner, I want generated titles and summaries overwritten in place only when needed, so that the product stays simple.
42. As a project owner, I want durable case names rather than article-shaped titles, so that cases can absorb future events.
43. As a project owner, I want neutral factual wording, so that automatic public pages do not become sensational or legally unsafe.

## Implementation Decisions

- The MVP publishes automatically after an initial backfill reaches a ready-enough checkpoint.
- Human review, feedback forms, correction tooling, duplicate-case redirects, and advanced analytics are later work.
- Public output is Ukrainian only. Prompts are Ukrainian. Code and database naming remain English.
- `Case` means reader-facing dossier/topic. It is not an exclusive article cluster.
- One relevant article is enough to create a public case.
- Case-linked articles may exist without extracted events.
- Articles can link to multiple cases. Events can link to multiple cases. Entities can link to multiple cases.
- Explicit case relations support `parent_child`, `related`, and `possible_duplicate`.
- `Entity` is one global typed model with canonical name, aliases, type, and Ukrainian description.
- `Event` is one global strict real-world occurrence. Related developments are separate events.
- One supporting article is enough for a public event if provenance is preserved.
- Event relations are out of scope for MVP.
- Direct entity-event relations are out of scope for MVP.
- Ingestion stores raw HTML, extracted text, source metadata, detected source language, and remote image URLs.
- Article dedupe starts with canonical URL and normalized URL uniqueness.
- Article clicks in the public UI go to the original source.
- Source type is context and display metadata, not a trust score.
- Relevance filtering uses a local binary classifier before any LLM calls.
- The first likely classifier shape is logistic regression over title, lead, and the first fixed-size text window with TF-IDF word and character ngrams.
- DVC tracks large model binaries under `artifacts/models/`. Real artifacts stay outside Git; manifests and `.dvc` pointers are tracked.
- LLM article cards are provisional structured understanding, not final global identity.
- Article cards separate classifier relevance from case candidacy. Non-case
  cards retain a summary but have no provisional events, entities, or case
  signature terms.
- Article-card extraction is limited to the main article and excludes related
  articles, recommendations, boilerplate, and unrelated background.
- Article-case resolution happens before entity and event resolution.
- Entity and event resolvers receive all linked cases and assign each resolved item only to relevant cases.
- Direct `case_entities` and `case_events` are materialized from article-level scoped links.
- Qdrant has rebuildable collections for case cards, entity cards, and event cards.
- LLM prompts live as plain files in the ML worker area.
- LLM outputs are structured JSON validated by Pydantic.
- Invalid LLM JSON is repaired once, then the task is marked failed.
- Generated public fields are overwritten in place for MVP. Store run and version metadata for debugging and manual reprocessing.
- Background work uses one generic PostgreSQL jobs table with row locking.
- LLM stages should be separate jobs to make retries and inspection easier.
- The public API reads current rows directly; there are no published snapshots in MVP.
- Case view counting is anonymous aggregate counting.

## Testing Decisions

- Tests should verify external behavior and durable contracts, not private implementation details.
- Ingestion tests should cover URL normalization, canonical dedupe, extraction result validation, source language persistence, and image URL extraction fallback behavior.
- Classifier tests should cover the inference boundary: given extracted article fields and a loaded model interface, the system persists binary relevance, score, and classifier version.
- LLM contract tests should validate Pydantic schemas against representative successful, repairable, and invalid outputs.
- Resolution tests should cover many-to-many article-case links, scoped entity/event assignment to relevant cases, and materialized case links.
- Event identity tests should cover strict deduplication: same real-world occurrence merges, related developments remain separate.
- Backend tests should cover public feed sorting, case page composition, entity page composition, and anonymous view counter behavior.
- Frontend tests should focus on visible user behavior: case feed modes, timeline source popups, original-source links, entity pages, and disclaimer rendering.
- Existing smoke-test style in the repo can remain for service startup, but future pipeline tests need domain fixtures.

## Out of Scope

- Mandatory human review queue.
- User accounts, personalization, or per-user analytics.
- Article pages hosted by Shkandal.
- Image proxying or caching.
- Multilingual public UI or generated content.
- Event relations such as appeal/reaction/caused-by/corrects.
- Direct entity-event relationship modeling.
- Automatic reprocessing when prompts, classifiers, or extraction versions change.
- Redis or external queue infrastructure.
- Full archive crawling beyond the planned controlled one-year backfill.
- Model registry beyond the current DVC-tracked local artifact setup.

## Further Notes

The repo currently has foundation scaffolding only: service shells, common
config/logging, Docker Compose, and smoke tests. The next implementation step is
the PostgreSQL schema and migration layer, because the article/evidence graph is
the central contract shared by ingestion, ML workers, backend, and frontend.

This PRD has been broken into GitHub issues #1 through #12 in
`serpanchyk/shkandal`.
