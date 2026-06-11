# Shkandal

Shkandal is a Ukrainian-language platform for turning scattered Ukrainian media and institutional articles about public scandals, corruption investigations, political cases, and socially important stories into reader-facing dossiers.

The project is built for Ukraine and about Ukraine. Public UI text, generated case titles, summaries, event descriptions, and entity descriptions are Ukrainian only. Code, database fields, and service names stay English.

## Product Direction

A normal news feed loses context quickly. One public case can develop for months, but articles are scattered across dates, sources, headlines, and institutions.

Shkandal should show readers a living case page that answers:

- what this case is about;
- who and which organizations are involved;
- what happened in chronological order;
- which source articles support each event;
- how this case connects to broader or more specific cases.

The first public version is automatic. The system should ingest articles, classify relevance, resolve cases, entities, and events, then update public pages without a mandatory human review queue. Later review and correction tools can be added, but they are not part of the MVP control flow.

Local Docker Compose configuration uses three ignored env files copied from
tracked examples: root `.env` for shared application settings,
`infra/postgres/.env` for database bootstrap credentials, and
`infra/litellm/.env` for provider API keys. See `docs/run-project.md` for setup.

## Core Concepts

### Case

A `Case` is a reader-facing dossier/topic, not an exclusive article cluster.

Examples:

- Mindichgate / Midas;
- Dynasty cooperative corruption case;
- Oleksiy Chernyshov related case lines;
- Denys Komarnytskyi / Clean City;
- Bill No. 14057 and risks for investigative journalism.

Cases can overlap. One article can belong to multiple cases. One event can be relevant to multiple cases.

One relevant article is enough to create a public case. The system optimizes for coverage and speed, with source provenance visible to readers.

Case relationships are explicit:

- `related` for shared central actors or specific accountability themes;
- `possible_duplicate` for later automatic or manual merge handling.

### Article

An `Article` is an ingested source item. It remains the evidence source, but public case pages should query direct case links after processing.

An article can be linked to a case even when it does not create a concrete extracted event. Those articles can still appear in the case source section, but the timeline should show only resolved events.

Articles store:

- source and source type;
- original URL and canonical/normalized URL;
- title, lead, publication date, language;
- extracted text;
- raw HTML;
- remote image URL and image metadata when available.

Article clicks in the public UI go directly to the original media or institution page. Shkandal does not publish copied full article pages in the MVP.

### Entity

An `Entity` is a global person, organization, institution, company, political party, informal group, or unknown actor. There is one `entities` table with an `entity_type`, canonical Ukrainian name, aliases, and a short Ukrainian description.

Entity pages are part of the product. They should show the entity description, related cases, and articles where the entity is mentioned. Entity descriptions are generated only from articles connected to public cases.

### Event

An `Event` is a global real-world occurrence. Event identity is strict: two mentions are the same event only when they refer to the same occurrence with compatible date, actors, institution, action, and object.

Related developments are separate events. For example, a court setting bail and an appeal court changing bail are different events in the same case timeline.

Events do not need direct `event_relations` in the MVP. Shared cases and entities are enough for first timelines.

## Public Pages

### Homepage

The homepage should feel modern and live, not like an old archive. The MVP should expose a case feed with sorting modes:

- `latest`: most recently updated cases;
- `newest`: recently created cases;
- `popular`: most viewed cases by anonymous aggregate counters;
- `biggest`: cases with the most linked articles;
- `trending`: cases with the highest recent linked-article velocity.

The implemented ranking contract defines `latest` as newest linked-article
publication time, `trending` as linked articles published in the previous seven
days, `popular` as all-time aggregate views, `biggest` as linked-article count,
and `newest` as Case creation time. The homepage defaults to `trending`.
Undated articles remain evidence but do not affect `latest` or `trending`.
Typo-tolerant Case-title search uses PostgreSQL trigram similarity.

Future homepage ideas include live event streams, infographics, and real-time update blocks.

### Case Page

A case page should contain:

- stable Ukrainian case title;
- short neutral Ukrainian summary;
- people and organizations involved;
- chronological event timeline;
- event source popup with linked articles;
- compact linked-articles/source section near the bottom;
- short automatic-generation disclaimer.
- compact `Джерела справи` logo strip for all supporting Source types.

Case titles and summaries should be durable identity fields, not rewritten after every new article. Most change should appear through the event timeline. Regenerate title/summary only when the meaning of the case changes.

Generated tone must be neutral and factual. The system should distinguish allegations, investigations, charges, court decisions, and proven facts. It must not declare guilt unless sources report a final legal finding.

Suggested disclaimer:

```text
Сторінка автоматично зібрана з відкритих джерел. Події та згадані особи й організації мають посилання на матеріали, на основі яких їх додано.
```

### Entity Page

An entity page should contain:

- canonical Ukrainian name;
- aliases;
- entity type;
- short Ukrainian description;
- related cases;
- articles where the entity is mentioned.

## Pipeline

### 1. Discover and Fetch

The ingestion worker starts from a small curated source list. Sources can be media, institutions, courts, NGOs, or other public sources. Source type is context and UI metadata, not an authority score.

Initial discovery methods:

- `sitemap.xml`;
- RSS/Atom feeds;
- manually configured source sections;
- include/exclude URL patterns.

The MVP runs a controlled one-year backfill before first public launch, then continues forward ingestion with a full-source pass every two hours. Date-bounded backfills use a higher source discovery cap than daily runs so archive traversal is not truncated too early. Fetching can happen in any order, but LLM resolution during backfill should process relevant articles oldest-to-newest by `published_at`.

### 2. Extract and Store

The ingestion pipeline stores extracted text and raw HTML for all articles, including irrelevant ones. Raw HTML lets the project improve extraction later without re-crawling.

Extraction is generic-first, with site-specific selectors only as fallback.
Publication dates are extracted from article HTML metadata and can be repaired
later from stored raw HTML without refetching articles.

### 3. Classify Relevance

Relevance filtering is a local binary ML classifier before any LLM calls. The intended first model is a lightweight classifier such as logistic regression trained on the user's dataset.

Classifier input should be:

- title;
- lead;
- first fixed-size window of extracted text.

The likely first feature approach is TF-IDF word ngrams plus character ngrams.
DVC tracks large model binaries under `artifacts/models/`, while Git tracks the
small metadata manifests and DVC pointer files. Real model artifacts stay outside
Git history.

Irrelevant articles remain stored with `is_relevant=false` for debugging, evaluation, and future reprocessing.

### 4. Create Provisional Article Card

For classifier-positive articles, the LLM creates a compact Ukrainian article
card with structured JSON validated by Pydantic. The LLM applies a stricter
`is_case_candidate` gate so rankings, essays, generic news, and similar material
remain available as summaries without producing case events or entities.

The card contains:

- Ukrainian title or cleaned title;
- short Ukrainian summary;
- case-candidate decision and fixed noise reason;
- main event title for case candidates;
- up to eight case-relevant normalized entities;
- one to three provisional normalized events;
- up to eight case-signature terms.

The provisional entities and events are not final global identities yet.
Non-case cards have empty event, entity, and case-signature lists.

### 5. Resolve Cases

The article card is embedded and used to retrieve candidate cases from Qdrant. The LLM then resolves article-case relationships:

- link the article to one or more existing cases;
- create one or more new durable reader-facing cases;
- create explicit case relations when useful.

Every case-candidate article must link to or create at least one case. Empty
resolution is invalid. Case mutation is serialized, and new or changed case
vectors must be written before the PostgreSQL mutation commits.

Case titles should be broader durable dossier names, not one-off event headlines.
Existing case copy is refreshed by a unique case-scoped job after each new
article link. The job always refreshes the summary and replaces the title only
when the current title is materially inadequate.

### 6. Resolve Entities

After article-case links exist, provisional entities are embedded and compared against the Qdrant entity collection. The LLM resolves each provisional entity to an existing global entity or creates a new entity.

The resolver receives all linked cases and assigns each resolved entity only to the cases where it is relevant. The system then materializes direct `case_entities` links.

Public entity lists must include only entities directly mentioned in at least one supporting article. Aliases can be deduplicated and stored on the entity row for MVP.

### 7. Resolve Events

After article-case links exist, provisional events are embedded and compared against the Qdrant event collection. The LLM resolves each provisional event to an existing global event or creates a new event.

The resolver receives all linked cases and assigns each resolved event only to the cases where it is relevant. The system then materializes direct `case_events` links.

Event dates use the best-effort extracted occurrence date. Unknown occurrence
dates remain unknown; article publication time is provenance and an explicit
timeline-ordering fallback, never the Event date.

One supporting article is enough for a public event, as long as the event keeps article provenance.

### 8. Update Cards and Public Data

PostgreSQL is the source of truth. Qdrant stores rebuildable vector indexes:

- case cards;
- entity cards;
- event cards.

Generated fields are overwritten in place for MVP. Store enough run metadata to debug bad generations: LLM run, prompt name/version, model, status, and raw or repaired output.

## Data Model Direction

The MVP PostgreSQL schema is implemented with SQLAlchemy models in
`packages/database` and Alembic migrations owned by that package.

Important MVP tables and relationships:

- `sources`;
- `articles`;
- `article_relevance`;
- `article_cards`;
- `cases`;
- `case_articles`;
- `case_relations`;
- `entities`;
- `article_entities`;
- `article_entity_cases`;
- `case_entities`;
- `events`;
- `article_events`;
- `article_event_cases`;
- `case_events`;
- `llm_runs`;
- `jobs`;
- `case_view_counters`.

`case_entities` and `case_events` are direct materialized public-page links. They are created from article-level LLM resolution plus article-case context, not from an independent manual curation step.

`case_articles` stays simple in the MVP: it records that an article belongs to a case and why, without roles such as primary, secondary, or background. Entity and event relevance carries the more specific case-scoped meaning.

There is no direct `entity_event` relationship in the MVP. Cases can show entities and events independently, with event text naturally mentioning actors when needed.

## LLM Contracts

Prompts live as plain Ukrainian files in the repo, owned by `worker-ml`.
LangChain consumes those files inside individual LLM tasks for prompt handling
and simple chains; it does not own job orchestration, persistence, retries, or
database mutation.

LLM outputs must be structured JSON validated by Pydantic. Invalid output should
be repaired once with a schema-only repair prompt. If repair fails, mark the LLM
task failed and keep it eligible for later reprocessing.

All runtime LLM calls go through the LiteLLM proxy. `worker-ml` requests logical
per-stage aliases such as `shkandal-article-card` and `shkandal-repair`; the
proxy owns provider credentials, throttling, routing, and fallback policy. The
tracked proxy configuration maps all aliases to one shared MamayLM deployment
through Lapatonia with a combined 60 RPM limit and falls back to Amazon Bedrock
Gemma 3 27B when the primary provider fails. Primary-provider retries are
disabled, so fallback is attempted immediately. Four Lapatonia failures within
one hour start a shared one-hour in-memory cooldown; restarting `llm-proxy`
clears it.
Provider HTTP `429` responses that still reach `worker-ml` after proxy routing
create a durable shared LLM cooldown: the rejected job is deferred without
consuming an attempt and the current ML pass exits.
Explicit `Retry-After` values are honored; otherwise two ambiguous `429`
responses within 15 minutes infer a one-hour cooldown. Other provider errors
remain per-job failures. LLM requests time out after five minutes.

For the initial historical run, `worker-ml --backfill` drains all supported ML
jobs and waits through deferred retries or provider cooldowns. It preserves
exhausted failed jobs for inspection and exits nonzero when any remain.

## Architecture

The project is split into these services:

- `frontend`: Next.js public UI for case pages, entity pages, and feed;
- `backend`: FastAPI public API and application business boundary;
- `worker-ingestion`: curated source discovery, fetching, extraction, URL identity normalization, image URL extraction;
- `worker-ml`: relevance classifier, article cards, E5-small embeddings, Qdrant
  vector integration, and LLM Case/Entity/Event resolution;
- `postgres`: source-of-truth relational database and MVP job store;
- `qdrant`: rebuildable 384-dimensional vector index for cases, entities, and events.
- `llm-proxy`: LiteLLM proxy for provider routing, throttling, and fallback policy.

The shared `packages/database` workspace package owns async SQLAlchemy models,
session helpers, and Alembic migrations. Local PostgreSQL data is stored in the
Compose `postgres-data` named volume and survives container restarts unless
volumes are explicitly removed.

Redis is excluded from the MVP. Background work starts with one generic PostgreSQL `jobs` table and row locking. LLM stages should be separate jobs so they can be retried and inspected independently.

## Launch Approach

The first public release should happen after a one-year curated-source backfill completes or reaches a manually chosen "ready enough" checkpoint. Public pages can update automatically after launch.

The project currently runs on servers provided by the Department of Artificial Intelligence Systems at Lviv Polytechnic National University and uses Lapatonia LLM infrastructure.

## Later

Planned later layers:

- simple "Повідомити про помилку" feedback link or form;
- human review/correction tooling;
- automatic merge handling for duplicate cases with redirects/aliases;
- event relations such as appeal/reaction/correction;
- image proxying or caching if needed;
- richer analytics beyond anonymous aggregate counters.
