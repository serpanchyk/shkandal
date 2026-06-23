from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import shkandal_backend.public_repository as public_repository
from shkandal_backend.public_repository import SqlAlchemyPublicRepository
from shkandal_backend.schemas import ArticlePreview, SourcePreview
from shkandal_database.models import Article, Case, Entity, Event, Source
from sqlalchemy.ext.asyncio import AsyncSession


class FakeImageUrlChecker:
    def __init__(self, available_url: str | None = None) -> None:
        self.available_url = available_url
        self.calls: list[list[str]] = []

    async def first_available(self, urls: list[str]) -> str | None:
        self.calls.append(urls)
        return self.available_url


class FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows

    def scalars(self) -> "FakeResult":
        return self


class FakeSession:
    def __init__(
        self,
        *,
        scalars: list[Any] | tuple[Any, ...] = (),
        executes: list[list[Any]] | tuple[list[Any], ...] = (),
    ) -> None:
        self.scalar_values = list(scalars)
        self.execute_values = list(executes)
        self.executed_statements: list[Any] = []
        self.commit = AsyncMock()

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        return None

    async def scalar(self, statement: Any) -> Any:
        return self.scalar_values.pop(0)

    async def execute(self, statement: Any) -> FakeResult:
        self.executed_statements.append(statement)
        return FakeResult(self.execute_values.pop(0))

    async def scalars(self, statement: Any) -> FakeResult:
        self.executed_statements.append(statement)
        return FakeResult(self.execute_values.pop(0))


def _repository(
    session: FakeSession,
    image_url_checker: FakeImageUrlChecker | None = None,
) -> SqlAlchemyPublicRepository:
    return SqlAlchemyPublicRepository(
        lambda: session,  # type: ignore[arg-type]
        image_url_checker or FakeImageUrlChecker(),
    )


def _case() -> Case:
    return Case(
        id=uuid4(),
        slug="case-a",
        title_uk="Справа А",
        summary_uk="Опис.",
        status="active",
        last_updated_at=datetime(2026, 6, 11, tzinfo=UTC),
        article_count=2,
        event_count=1,
    )


def _source() -> Source:
    return Source(
        id=uuid4(),
        slug="pravda",
        name="Українська правда",
        source_type="media",
        base_url="https://www.pravda.com.ua",
        logo_path="/sources/pravda.png",
    )


def _article_preview() -> ArticlePreview:
    return ArticlePreview(
        title="Матеріал",
        url="https://example.com/article",
        published_at=None,
        image_url=None,
        source=SourcePreview(
            slug="source",
            name="Source",
            source_type="media",
            homepage_url="https://example.com",
            logo_path=None,
        ),
    )


@pytest.mark.parametrize("sort", ["latest", "newest", "popular", "biggest", "trending"])
async def test_case_feed_builds_each_ranking(sort) -> None:
    case_row = _case()
    image_url = "https://example.com/image.jpg"
    session = FakeSession(scalars=[1], executes=[[(case_row, 7, [image_url])]])

    result = await _repository(session, FakeImageUrlChecker(image_url)).case_feed(
        sort=sort,
        query=None,
        page=1,
    )

    assert result.sort == sort
    assert result.items[0].view_count == 7
    assert result.items[0].image_url == "https://example.com/image.jpg"


async def test_case_feed_searches_case_entity_and_event_text() -> None:
    session = FakeSession(scalars=[0], executes=[[]])

    result = await _repository(session).case_feed(sort="trending", query=" офіс ", page=2)
    sql = str(
        session.executed_statements[0].compile(
            compile_kwargs={"literal_binds": True},
        )
    )

    assert result.query == "офіс"
    assert result.page == 2
    assert result.items == []
    assert "cases.title_uk" in sql
    assert "cases.summary_uk" in sql
    assert "case_entities" in sql
    assert "entities.canonical_name_uk" in sql
    assert "entities.description_uk" in sql
    assert "entities.aliases" in sql
    assert "case_events" in sql
    assert "events.title_uk" in sql
    assert "events.description_uk" in sql
    assert "events.location_uk" in sql
    assert "similarity" in sql
    assert "LIKE" in sql
    assert "%офіс%" in sql
    assert "ORDER BY greatest" in sql


async def test_case_feed_uses_first_linked_non_empty_article_image() -> None:
    session = FakeSession(scalars=[0], executes=[[]])

    await _repository(session).case_feed(sort="trending", query=None, page=1)

    sql = str(
        session.executed_statements[0].compile(
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "articles.remote_image_url IS NOT NULL" in sql
    assert "articles.remote_image_url != ''" in sql
    assert "array_agg(articles.remote_image_url ORDER BY case_articles.created_at ASC" in sql


async def test_case_feed_uses_first_available_article_image() -> None:
    case_row = _case()
    dead_url = "https://example.com/dead.jpg"
    live_url = "https://example.com/live.jpg"
    checker = FakeImageUrlChecker(live_url)
    session = FakeSession(scalars=[1], executes=[[(case_row, 7, [dead_url, live_url])]])

    result = await _repository(session, checker).case_feed(sort="trending", query=None, page=1)

    assert checker.calls == [[dead_url, live_url]]
    assert result.items[0].image_url == live_url


async def test_case_feed_returns_no_image_when_linked_articles_have_none() -> None:
    case_row = _case()
    session = FakeSession(scalars=[1], executes=[[(case_row, 7, None)]])

    result = await _repository(session).case_feed(sort="trending", query=None, page=1)

    assert result.items[0].image_url is None


async def test_latest_events_returns_known_dated_rows() -> None:
    event = Event(
        id=uuid4(),
        slug="event-a",
        title_uk="Подія",
        event_year=2026,
        event_month=6,
        event_day=11,
        event_date_precision="day",
        location_uk="Київ",
    )

    result = await _repository(FakeSession(executes=[[event]])).latest_events()

    assert result[0].title_uk == "Подія"
    assert result[0].event_year == 2026
    assert result[0].location_uk == "Київ"


async def test_case_page_composes_public_helpers(monkeypatch) -> None:
    case_row = _case()
    session = FakeSession(scalars=[case_row])
    monkeypatch.setattr(public_repository, "_is_public_case", AsyncMock(return_value=True))
    monkeypatch.setattr(
        public_repository,
        "_case_articles",
        AsyncMock(return_value=[_article_preview()]),
    )
    monkeypatch.setattr(public_repository, "_case_sources", AsyncMock(return_value=[]))
    monkeypatch.setattr(public_repository, "_case_entities", AsyncMock(return_value=[]))
    monkeypatch.setattr(public_repository, "_case_events", AsyncMock(return_value=[]))
    monkeypatch.setattr(public_repository, "_other_cases", AsyncMock(return_value=[]))
    monkeypatch.setattr(public_repository, "_case_view_count", AsyncMock(return_value=9))

    result = await _repository(session).case_page("case-a")

    assert result is not None
    assert result.view_count == 9
    assert result.articles[0].title == "Матеріал"


async def test_case_page_hides_missing_or_unready_case(monkeypatch) -> None:
    assert await _repository(FakeSession(scalars=[None])).case_page("missing") is None

    monkeypatch.setattr(public_repository, "_is_public_case", AsyncMock(return_value=False))
    assert await _repository(FakeSession(scalars=[_case()])).case_page("hidden") is None


async def test_increment_case_view_commits_and_returns_total(monkeypatch) -> None:
    case_id = uuid4()
    session = FakeSession(scalars=[case_id], executes=[[]])
    monkeypatch.setattr(public_repository, "_case_view_count", AsyncMock(return_value=12))

    result = await _repository(session).increment_case_view("case-a")

    assert result == 12
    session.commit.assert_awaited_once()


async def test_increment_case_view_hides_unready_case() -> None:
    assert await _repository(FakeSession(scalars=[None])).increment_case_view("missing") is None


async def test_sitemap_combines_case_and_entity_routes() -> None:
    updated_at = datetime(2026, 6, 11, tzinfo=UTC)
    session = FakeSession(executes=[[("case-a", updated_at)], [("entity-a", updated_at)]])

    result = await _repository(session).sitemap_entries()

    assert [entry.path for entry in result] == ["/cases/case-a", "/entities/entity-a"]


def test_preview_helpers_expose_source_and_article_contracts() -> None:
    source = _source()
    article = Article(
        id=uuid4(),
        source_id=source.id,
        url="https://example.com/article",
        identity_url="https://example.com/article",
        title=None,
    )

    source_preview = public_repository._source_preview(source, 3)
    article_preview = public_repository._article_preview(article, source)
    other_preview = public_repository._other_case(_case())

    assert source_preview.article_count == 3
    assert article_preview.title == article.url
    assert other_preview.slug == "case-a"


async def test_entity_page_hides_missing_or_undescribed_entity() -> None:
    assert await _repository(FakeSession(scalars=[None])).entity_page("missing") is None
    entity = Entity(
        id=uuid4(),
        slug="entity-a",
        entity_type="person",
        canonical_name_uk="Особа",
        aliases=[],
        description_uk=None,
    )
    assert await _repository(FakeSession(scalars=[entity])).entity_page("entity-a") is None


async def test_entity_page_composes_public_case_and_article() -> None:
    source = _source()
    article = Article(
        id=uuid4(),
        source_id=source.id,
        url="https://example.com/article",
        identity_url="https://example.com/article",
        title="Матеріал",
    )
    entity = Entity(
        id=uuid4(),
        slug="entity-a",
        entity_type="person",
        canonical_name_uk="Особа",
        aliases=["Псевдонім"],
        description_uk="Опис.",
    )
    session = FakeSession(
        scalars=[entity],
        executes=[[_case()], [(article, source)]],
    )

    result = await _repository(session).entity_page("entity-a")

    assert result is not None
    assert result.aliases == ["Псевдонім"]
    assert result.cases[0].slug == "case-a"
    assert result.articles[0].title == "Матеріал"


async def test_public_predicate_and_view_count_helpers() -> None:
    case_row = _case()
    readiness_session = FakeSession(scalars=[True])
    views_session = FakeSession(scalars=[14])

    assert await public_repository._is_public_case(readiness_session, case_row) is True  # type: ignore[arg-type]
    assert await public_repository._case_view_count(views_session, case_row.id) == 14  # type: ignore[arg-type]


async def test_case_article_source_and_entity_helpers() -> None:
    case_id = uuid4()
    source = _source()
    article = Article(
        id=uuid4(),
        source_id=source.id,
        url="https://example.com/article",
        identity_url="https://example.com/article",
        title="Матеріал",
    )
    entity = Entity(
        id=uuid4(),
        slug="entity-a",
        entity_type="person",
        canonical_name_uk="Особа",
        aliases=[],
        description_uk="Опис.",
    )

    articles = await public_repository._case_articles(
        cast(AsyncSession, FakeSession(executes=[[(article, source)]])),
        case_id,
    )
    sources = await public_repository._case_sources(
        cast(AsyncSession, FakeSession(executes=[[(source, 2)]])),
        case_id,
    )
    entities = await public_repository._case_entities(
        cast(AsyncSession, FakeSession(executes=[[(entity, 3)]])),
        case_id,
    )

    assert articles[0].title == "Матеріал"
    assert sources[0].article_count == 2
    assert entities[0].mention_count == 3


async def test_other_cases_helper_returns_only_query_rows() -> None:
    session = FakeSession(executes=[[_case()]])
    other_cases = await public_repository._other_cases(cast(AsyncSession, session), uuid4())

    assert other_cases[0].slug == "case-a"
    statement = session.executed_statements[0]
    assert statement._limit_clause.value == 10
    query = str(statement)
    assert "case_articles" in query
    assert "case_events" in query
    assert "case_entities" in query


async def test_case_events_helper_composes_supporting_articles() -> None:
    source = _source()
    article = Article(
        id=uuid4(),
        source_id=source.id,
        url="https://example.com/article",
        identity_url="https://example.com/article",
        title="Матеріал",
    )
    event = Event(
        id=uuid4(),
        slug="event-a",
        title_uk="Подія",
        description_uk="Опис.",
        event_year=2026,
        event_month=6,
        event_day=11,
        event_date_precision="day",
    )
    session = cast(
        AsyncSession,
        FakeSession(executes=[[event], [(article, source)]]),
    )

    result = await public_repository._case_events(session, uuid4())

    assert result[0].title_uk == "Подія"
    assert result[0].supporting_articles[0].title == "Матеріал"
