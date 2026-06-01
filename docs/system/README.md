# System Overview

Shkandal processes Ukrainian media articles through a pipeline:

1. discover article URLs;
2. fetch and extract article content;
3. filter irrelevant news;
4. create compact article cards;
5. retrieve candidate cases through vector search;
6. resolve cases, people, and events with deterministic checks and LLM calls;
7. queue ambiguous decisions for human review;
8. publish clean case pages for readers.

The current implementation is a foundation scaffold. It defines service
boundaries and runtime wiring but does not yet implement the article pipeline.
