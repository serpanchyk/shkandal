# Shkandal

Shkandal is a platform for tracking public cases, political scandals, corruption investigations, and socially important stories in Ukrainian media.

The project collects articles from open sources, filters relevant news, groups articles into cases, extracts key actors, and builds a timeline of how each case develops over time.

## Idea

A normal news feed loses context quickly. One scandal can develop for months, but articles about it are scattered across different media, dates, and headlines.

Shkandal tries to turn scattered articles into a structured case file:

- what happened;
- who is involved;
- what the key events are;
- how the case developed over time;
- which articles belong to it.

## What Counts as a Case

The project does not try to track every news article.

A good case usually has:

- named actors, suspects, officials, victims, or institutions;
- a clear public, political, or anti-corruption interest;
- development over time;
- enough context for a reader to follow the story.

One-off anonymous crime reports without named actors or follow-up are usually treated as noise.

## How It Works

Shkandal processes news articles through an automated pipeline that combines classic data engineering, vector search, machine learning, and LLM-based reasoning.

The goal is not just to collect articles, but to understand whether a new article belongs to an existing public case, starts a new case, or should be ignored as irrelevant noise.

### 1. Article Discovery

The ingestion worker collects article URLs from Ukrainian media sources.

Supported discovery methods include:

- sitemap.xml files;
- manually configured source sections.

The source configuration mostly describes where to find article URLs and which URL patterns should be included or excluded. The project tries to avoid hardcoding full article parsers for every media website.

### 2. Article Fetching and Extraction

After a URL is discovered, the system downloads the page and extracts the article content.

The extraction pipeline is generic-first:

1. article text is extracted with generic content extraction tools;
2. site-specific selectors are used only as a fallback;

The system checks whether the extracted article has a valid title, enough text, publication date, source, and acceptable boilerplate ratio.

Raw HTML can be stored so extraction can be improved later without crawling the same page again.

### 3. Relevance Filtering

Not every article is useful for Shkandal.

A relevance classifier filters out unrelated news such as weather, sports, lifestyle, entertainment, generic foreign policy, or one-off crime reports without public significance.

Relevant articles usually involve:

- Ukrainian domestic politics;
- corruption;
- public officials;
- courts and law enforcement;
- investigative journalism;
- scandals with named actors;
- important institutional decisions;
- major public conflicts.

Articles that do not pass the relevance filter are marked as noise and are not processed further.

### 4. Article Card Generation

For every relevant article, the system creates a compact article card.

The article card contains only the most important information:

- title;
- lead or summary;
- source;
- publication date;
- short text excerpt;
- detected names and organizations.

This card is used instead of sending the full article everywhere. It keeps processing cheaper and makes retrieval more stable.

### 5. Case Retrieval

Each public case has a short embedding-friendly case card.

A case card usually contains:

- case title;
- short description;
- main actors;
- important organizations;
- keywords;
- known subtopics.

The article card is embedded and compared with existing case cards in vector space.

This gives the system a list of candidate cases that may be related to the article.

For example, an article about Timūr Mindich, Energoatom, bail, searches in Israel, or Quartal 95 should retrieve the large case:

Mindichgate / Midas

The system uses retrieval only to find candidates. It does not blindly trust vector similarity.

6. Person and Event Resolution

The system also extracts people, organizations, and possible events from the article.

People are deduplicated globally. The same person should have one stable person_id even if they appear in multiple cases.

For example:

Oleksiy Chernyshov

may appear in several related storylines, but should still be represented as one person.

Events are deduplicated more carefully. Similar court decisions, bail changes, searches, resignations, or official statements may look close semantically but still be different events.

Event matching uses not only embeddings, but also:

main actors;
event type;
date;
institution;
related case;
source article.
7. LLM-Based Resolution

After retrieval, the LLM receives a compact context:

the article card;
candidate case cards or case digests;
candidate people;
candidate events.

The model then decides what should happen with the article:

attach it to an existing case;
create a new case;
link existing people;
create new people;
link existing events;
create new events;
mark the article as irrelevant.

It can be like 3 retrieves and 3 calls to llm

So overall it can be four calls for one article: article extraction, case resolving, actors resolving, events resolving.

8. Case Updating

When an article is attached to a case, the system updates the case data:

linked articles;
timeline events;
involved people;
related organizations;
case summary;
case card for future retrieval.

Large cases can also have internal subtopics.

For example, a mega-case like Mindichgate may include subtopics such as:

Energoatom corruption scheme;
Timūr Mindich and Oleksandr Tsukerman;
Herman Halushchenko and Svitlana Hrynchuk;
Oleksiy Chernyshov;
Quartal 95;
government crisis;
bail and court decisions;
pressure on NABU;
foreign assets of suspects.

Externally, this is still one case for the reader, but internally subtopics help keep retrieval and summaries manageable.

9. Human Review

Not every decision should be accepted automatically.

Low-confidence results are sent to a review queue.

Typical review cases include:

possible new case;
ambiguous case assignment;
possible duplicate person;
possible duplicate event;
article that may be relevant but lacks named actors;
article related to a mega-case but unclear subtopic.

The review interface helps prevent the database from being polluted with bad clusters, duplicate people, and useless one-off cases.

10. Reader-Facing Output

The final goal is to show the reader a clean case page.

A case page should answer:

what this case is about;
who the main actors are;
what happened first;
what changed later;
what the latest update is;
which articles support the timeline.

Instead of forcing users to search through a news feed, Shkandal provides a structured dossier for each public scandal.

## Architecture

The project is split into several main services:

- `frontend` — user interface;
- `backend` — main application API and business logic;
- `worker-ingestion` — article crawling, parsing, and normalization;
- `worker-ml` — classification, embeddings, retrieval, LLM processing, and deduplication;
- `postgres` — main relational database;
- `qdrant` — vector search index.

PostgreSQL is the source of truth. Qdrant is only a vector index and can be rebuilt from PostgreSQL if needed.

Redis is optional. For the MVP, background jobs can be stored directly in PostgreSQL using a `jobs` table with row locking. Redis can be added later for higher-throughput queues, caching, locks, or rate limiting.

## Main Entities

- `Article` — a single news article.
- `Case` — a public case or scandal.
- `Person` — an official, suspect, victim, journalist, businessperson, or other relevant actor.
- `Event` — a concrete development inside a case.
- `CaseCard` — a short embedding-friendly description used for retrieval.
- `CaseDigest` — a compact case summary used as LLM context.

## Example Cases

- Mindichgate / Midas;
- Oleksiy Chernyshov — MinRegion, bail, Dynasty cooperative;
- Denys Komarnytskyi — Clean City;
- Bill No. 14057 — risks for investigative journalism.

## Infrastructure

The project runs on servers provided by the Department of Artificial Intelligence Systems at Lviv Polytechnic National University and uses the LLM infrastructure of Lapatonia.

## Status

The project is under active development.

Current focus:

- building a stable ingestion pipeline;
- improving article-to-case clustering;
- deduplicating people and events;
- creating a review interface for uncertain decisions;
- generating clear case pages for readers.