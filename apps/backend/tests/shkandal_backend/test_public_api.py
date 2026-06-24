from datetime import UTC, datetime

import httpx
from shkandal_backend.app import create_app
from shkandal_backend.config import BackendConfig
from shkandal_backend.schemas import (
    ArticlePreview,
    CaseFeedItem,
    CaseFeedPage,
    CasePage,
    EntityPage,
    LatestEvent,
    OtherCasePreview,
    SitemapEntry,
    SourcePreview,
)


def _source() -> SourcePreview:
    return SourcePreview(
        slug="pravda",
        name="Українська правда",
        source_type="media",
        homepage_url="https://www.pravda.com.ua",
        logo_path="/sources/pravda.png",
        article_count=1,
    )


def _article() -> ArticlePreview:
    return ArticlePreview(
        title="Матеріал",
        url="https://www.pravda.com.ua/news/example",
        published_at=datetime(2026, 6, 11, tzinfo=UTC),
        image_url=None,
        source=_source(),
    )


class FakePublicRepository:
    def __init__(self) -> None:
        self.last_feed_call: tuple[str, str | None, int] | None = None

    async def case_feed(self, *, sort, query, page) -> CaseFeedPage:
        self.last_feed_call = (sort, query, page)
        return CaseFeedPage(
            items=[
                CaseFeedItem(
                    slug="case-a",
                    title_uk="Справа А",
                    summary_uk="Опис справи.",
                    latest_article_at=datetime(2026, 6, 11, tzinfo=UTC),
                    article_count=2,
                    view_count=5,
                    image_url=None,
                )
            ],
            sort=sort,
            query=query,
            page=page,
            page_size=20,
            total_items=1,
            total_pages=1,
        )

    async def case_page(self, slug: str) -> CasePage | None:
        if slug in {"missing", "merged-case"}:
            return None
        return CasePage(
            slug=slug,
            title_uk="Справа А",
            summary_uk="Опис справи.",
            latest_article_at=datetime(2026, 6, 11, tzinfo=UTC),
            article_count=1,
            event_count=0,
            view_count=5,
            sources=[_source()],
            entities=[],
            events=[],
            articles=[_article()],
            other_cases=[
                CaseFeedItem(
                    slug="related-case",
                    title_uk="Пов’язана справа",
                    summary_uk="Опис пов’язаної справи.",
                    latest_article_at=datetime(2026, 6, 10, tzinfo=UTC),
                    article_count=3,
                    view_count=8,
                    image_url="https://example.com/related.jpg",
                )
            ],
            disclaimer_uk="Автоматично зібрано.",
        )

    async def case_redirect_slug(self, slug: str) -> str | None:
        return "case-a" if slug == "merged-case" else None

    async def latest_events(self) -> list[LatestEvent]:
        return [
            LatestEvent(
                title_uk="Нова подія",
                event_year=2026,
                event_month=6,
                event_day=12,
                event_date_precision="day",
                location_uk=None,
            )
        ]

    async def entity_page(self, slug: str) -> EntityPage | None:
        if slug == "missing":
            return None
        return EntityPage(
            slug=slug,
            canonical_name_uk="Особа",
            entity_type="person",
            aliases=[],
            description_uk="Опис.",
            cases=[OtherCasePreview(slug="case-a", title_uk="Справа А", summary_uk="Опис.")],
            articles=[_article()],
        )

    async def increment_case_view(self, slug: str) -> int | None:
        return None if slug == "missing" else 6

    async def sitemap_entries(self) -> list[SitemapEntry]:
        return [
            SitemapEntry(
                path="/cases/case-a",
                updated_at=datetime(2026, 6, 11, tzinfo=UTC),
            )
        ]


def _client() -> tuple[httpx.AsyncClient, FakePublicRepository]:
    repository = FakePublicRepository()
    app = create_app(BackendConfig(service_name="backend-test"), repository)
    return (
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ),
        repository,
    )


async def test_feed_defaults_to_trending_and_accepts_search_paging() -> None:
    client, repository = _client()

    async with client:
        response = await client.get("/api/cases?sort=popular&query=справа&page=2")

    assert response.status_code == 200
    assert repository.last_feed_call == ("popular", "справа", 2)
    assert response.json()["items"][0]["slug"] == "case-a"


async def test_public_pages_and_view_counter_return_contracts() -> None:
    client, _ = _client()

    async with client:
        assert (await client.get("/api/events/latest")).json()[0]["title_uk"] == "Нова подія"
        case_page = (await client.get("/api/cases/case-a")).json()
        assert case_page["sources"][0]["logo_path"].endswith(".png")
        assert case_page["other_cases"][0] == {
            "slug": "related-case",
            "title_uk": "Пов’язана справа",
            "summary_uk": "Опис пов’язаної справи.",
            "latest_article_at": "2026-06-10T00:00:00Z",
            "article_count": 3,
            "view_count": 8,
            "image_url": "https://example.com/related.jpg",
        }
        assert (await client.get("/api/entities/person-a")).json()["canonical_name_uk"] == "Особа"
        assert (await client.post("/api/cases/case-a/views")).json() == {"view_count": 6}
        assert (await client.get("/api/sitemap")).json()[0]["path"] == "/cases/case-a"


async def test_missing_public_pages_return_404() -> None:
    client, _ = _client()

    async with client:
        assert (await client.get("/api/cases/missing")).status_code == 404
        assert (await client.get("/api/entities/missing")).status_code == 404
        assert (await client.post("/api/cases/missing/views")).status_code == 404


async def test_merged_case_redirects_to_surviving_case() -> None:
    client, _ = _client()

    async with client:
        response = await client.get("/api/cases/merged-case", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/api/cases/case-a"


async def test_feed_validates_query_page_and_sort() -> None:
    client, _ = _client()

    async with client:
        assert (await client.get("/api/cases?query=x")).status_code == 422
        assert (await client.get("/api/cases?page=0")).status_code == 422
        assert (await client.get("/api/cases?sort=unknown")).status_code == 422
