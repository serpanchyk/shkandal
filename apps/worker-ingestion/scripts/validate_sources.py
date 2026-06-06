"""Read-only validation for configured ingestion sources."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from urllib.parse import urljoin

from worker_ingestion.articles.extractor import extract_article
from worker_ingestion.config import IngestionConfig
from worker_ingestion.discovery.sitemap import discover_article_urls
from worker_ingestion.discovery.sources import CURATED_SOURCES, SourceConfig
from worker_ingestion.transport import HttpxFetcher


@dataclass(frozen=True)
class ValidationResult:
    source_slug: str
    check: str
    status: str
    url: str
    message: str | None = None
    details: dict[str, object] | None = None


async def validate_sources(
    *,
    source_slug: str | None,
    per_source_sample: int,
    request_timeout_seconds: float,
) -> list[ValidationResult]:
    config = IngestionConfig(
        max_sitemap_urls_per_source=max(per_source_sample * 3, 10),
        request_timeout_seconds=request_timeout_seconds,
    )
    fetcher = HttpxFetcher(config)
    sources = _select_sources(source_slug)
    results: list[ValidationResult] = []

    for source in sources:
        results.extend(await _validate_source(source, fetcher, config, per_source_sample))
    return results


async def _validate_source(
    source: SourceConfig,
    fetcher: HttpxFetcher,
    config: IngestionConfig,
    per_source_sample: int,
) -> list[ValidationResult]:
    results: list[ValidationResult] = []
    robots_url = urljoin(source.base_url, "/robots.txt")
    robots = await fetcher.fetch(robots_url)
    results.append(
        _endpoint_result(
            source,
            "robots",
            robots_url,
            robots.ok,
            status_code=robots.status_code,
            error=robots.error,
        )
    )

    for sitemap_url in source.sitemap_urls:
        sitemap = await fetcher.fetch(sitemap_url)
        results.append(
            _endpoint_result(
                source,
                "sitemap",
                sitemap_url,
                sitemap.ok,
                status_code=sitemap.status_code,
                error=sitemap.error,
            )
        )

    for feed_url in source.rss_urls:
        feed = await fetcher.fetch(feed_url)
        results.append(
            _endpoint_result(
                source,
                "rss",
                feed_url,
                feed.ok,
                status_code=feed.status_code,
                error=feed.error,
            )
        )

    for section_url in source.section_urls:
        section = await fetcher.fetch(section_url)
        results.append(
            _endpoint_result(
                source,
                "section",
                section_url,
                section.ok,
                status_code=section.status_code,
                error=section.error,
            )
        )

    discovered = await discover_article_urls(source, fetcher, config)
    if not discovered:
        results.append(
            ValidationResult(
                source_slug=source.slug,
                check="discovery",
                status="fail",
                url=source.base_url,
                message="No article URLs discovered.",
            )
        )
        return results

    for article_url in discovered[:per_source_sample]:
        response = await fetcher.fetch(article_url.url)
        if not response.ok:
            results.append(
                _endpoint_result(
                    source,
                    "article_fetch",
                    article_url.url,
                    False,
                    status_code=response.status_code,
                    error=response.error,
                )
            )
            continue
        extracted = extract_article(source, url=article_url.url, html=response.text)
        text = extracted.extracted_text or ""
        missing = []
        if not extracted.title:
            missing.append("title")
        if len(text) < 400:
            missing.append("text_length")
        if _looks_contaminated(text):
            missing.append("navigation_footer_contamination")

        results.append(
            ValidationResult(
                source_slug=source.slug,
                check="article_extract",
                status="ok" if not missing else "fail",
                url=article_url.url,
                message=", ".join(missing) if missing else None,
                details={
                    "discovery_method": article_url.discovery_method,
                    "identity_url": extracted.identity_url,
                    "title_present": extracted.title is not None,
                    "published_at_present": extracted.published_at is not None,
                    "text_length": len(text),
                },
            )
        )

    return results


def _endpoint_result(
    source: SourceConfig,
    check: str,
    url: str,
    ok: bool,
    *,
    status_code: int,
    error: str | None,
) -> ValidationResult:
    return ValidationResult(
        source_slug=source.slug,
        check=check,
        status="ok" if ok else "fail",
        url=url,
        message=error,
        details={"status_code": status_code},
    )


def _looks_contaminated(text: str) -> bool:
    lowered = text.lower()
    noise = ("пошук", "меню", "підписатися", "cookie", "copyright")
    return len(text) > 0 and sum(1 for marker in noise if marker in lowered) >= 3


def _select_sources(source_slug: str | None) -> tuple[SourceConfig, ...]:
    if source_slug is None:
        return CURATED_SOURCES
    return tuple(source for source in CURATED_SOURCES if source.slug == source_slug)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate configured Shkandal sources.")
    parser.add_argument("--source", dest="source_slug")
    parser.add_argument("--sample", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=8.0)
    args = parser.parse_args()
    started_at = datetime.now(UTC)
    results = asyncio.run(
        validate_sources(
            source_slug=args.source_slug,
            per_source_sample=args.sample,
            request_timeout_seconds=args.timeout,
        )
    )
    payload = {
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "results": [asdict(result) for result in results],
    }
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
    sys.stdout.write("\n")
    if any(result.status == "fail" for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
