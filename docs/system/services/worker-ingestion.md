# Worker Ingestion

The ingestion worker owns source discovery, page fetching, extraction, and
article normalization.

Planned responsibilities:

- read a small curated source list;
- discover URLs from sitemaps and configured source sections;
- apply include/exclude URL patterns;
- normalize and deduplicate URLs by canonical URL and normalized URL;
- fetch and store raw HTML for all articles;
- extract title, lead, publication date, source language, extracted text, and source metadata;
- extract remote image URL and image metadata when available;
- keep irrelevant articles in PostgreSQL after classification for debugging and reprocessing.

Source type is stored as context and UI metadata, not as an authority score.
Expected source types include media, institution, court, NGO, and other.

The current implementation is a runnable async process shell with configuration
and structured startup logging.
