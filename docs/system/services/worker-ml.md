# Worker ML

The ML worker owns the semantic processing pipeline after article extraction.

Planned responsibilities:

- run the local binary relevance classifier before any LLM calls;
- store classifier decision, score, and classifier version;
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
