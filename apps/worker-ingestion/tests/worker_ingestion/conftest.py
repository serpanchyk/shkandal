from datetime import UTC, datetime
from uuid import UUID, uuid4

from worker_ingestion.discovery.sources import SourceConfig
from worker_ingestion.persistence.articles import ArticleInput, SourceInput
from worker_ingestion.transport import FetchResult


class FakeFetcher:
    def __init__(self, responses: dict[str, FetchResult]) -> None:
        self.responses = responses
        self.requested_urls: list[str] = []

    async def fetch(self, url: str) -> FetchResult:
        self.requested_urls.append(url)
        return self.responses[url]


class FakeArticleRepository:
    def __init__(self) -> None:
        self.source_ids: dict[str, UUID] = {}
        self.articles: dict[str, ArticleInput] = {}

    async def ensure_source(self, source: SourceInput) -> UUID:
        source_id = self.source_ids.get(source.slug)
        if source_id is None:
            source_id = uuid4()
            self.source_ids[source.slug] = source_id
        return source_id

    async def skippable_identity_urls(
        self,
        identity_urls: set[str],
        *,
        max_attempts: int,
        now: datetime | None = None,
    ) -> set[str]:
        now = now or datetime.now(UTC)
        skippable: set[str] = set()
        for identity_url in set(self.articles).intersection(identity_urls):
            article = self.articles[identity_url]
            next_fetch_at = article.next_fetch_at
            if (
                article.fetch_status == "succeeded"
                or article.fetch_attempt_count >= max_attempts
                or (next_fetch_at is not None and next_fetch_at > now)
            ):
                skippable.add(identity_url)
        return skippable

    async def due_failed_article_urls(
        self,
        source_id: UUID,
        *,
        max_attempts: int,
        limit: int,
        now: datetime | None = None,
    ) -> tuple[str, ...]:
        now = now or datetime.now(UTC)
        return tuple(
            article.url
            for article in self.articles.values()
            if article.source_id == source_id
            and article.fetch_status == "failed"
            and article.fetch_attempt_count < max_attempts
            and (article.next_fetch_at is None or article.next_fetch_at <= now)
        )[:limit]

    async def upsert_article(self, article: ArticleInput) -> None:
        existing = self.articles.get(article.identity_url)
        if existing is None:
            self.articles[article.identity_url] = article
            return

        self.articles[article.identity_url] = ArticleInput(
            source_id=existing.source_id,
            url=existing.url,
            identity_url=existing.identity_url,
            title=article.title or existing.title,
            lead=article.lead or existing.lead,
            published_at=article.published_at or existing.published_at,
            fetched_at=article.fetched_at or existing.fetched_at,
            source_language=article.source_language or existing.source_language,
            raw_html=article.raw_html or existing.raw_html,
            extracted_text=article.extracted_text or existing.extracted_text,
            remote_image_url=article.remote_image_url or existing.remote_image_url,
            remote_image_metadata={
                **existing.remote_image_metadata,
                **article.remote_image_metadata,
            },
            source_metadata={**existing.source_metadata, **article.source_metadata},
            fetch_status=article.fetch_status,
            fetch_attempt_count=existing.fetch_attempt_count + 1,
            next_fetch_at=article.next_fetch_at,
            last_fetch_error=article.last_fetch_error,
        )


def source_config() -> SourceConfig:
    return SourceConfig(
        slug="example",
        name="Example Media",
        base_url="https://example.ua",
        sitemap_urls=("https://example.ua/sitemap.xml",),
        sitemap_url_patterns=(r"https://example\.ua/articles\.xml",),
        include_url_patterns=(r"https?://(www\.)?example\.ua/news/.+",),
    )


def fetch_result(url: str, body: str, content_type: str = "text/html") -> FetchResult:
    return FetchResult(
        url=url,
        status_code=200,
        content=body.encode(),
        text=body,
        headers={"content-type": content_type},
        fetched_at=datetime(2026, 6, 1, tzinfo=UTC),
    )


def failed_fetch_result(url: str) -> FetchResult:
    return FetchResult(
        url=url,
        status_code=500,
        content=b"",
        text="",
        headers={"content-type": "text/html"},
        fetched_at=datetime(2026, 6, 1, tzinfo=UTC),
        error="server_error",
    )
