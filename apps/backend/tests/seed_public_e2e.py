"""Seed a deterministic public graph for browser tests."""

from asyncio import run
from datetime import UTC, datetime
from uuid import UUID

from shkandal_database.config import DatabaseConfig
from shkandal_database.models import (
    Article,
    ArticleEntity,
    ArticleEntityCase,
    ArticleEvent,
    ArticleEventCase,
    Case,
    CaseArticle,
    CaseEntity,
    CaseEvent,
    Entity,
    Event,
    Source,
)
from shkandal_database.session import create_async_engine_from_config, create_async_sessionmaker

SOURCE_ID = UUID("10000000-0000-0000-0000-000000000001")
ARTICLE_ID = UUID("20000000-0000-0000-0000-000000000001")
CASE_ID = UUID("30000000-0000-0000-0000-000000000001")
ENTITY_ID = UUID("40000000-0000-0000-0000-000000000001")
EVENT_ID = UUID("50000000-0000-0000-0000-000000000001")
ARTICLE_ENTITY_ID = UUID("60000000-0000-0000-0000-000000000001")
ARTICLE_EVENT_ID = UUID("70000000-0000-0000-0000-000000000001")


async def seed() -> None:
    engine = create_async_engine_from_config(DatabaseConfig())
    session_factory = create_async_sessionmaker(engine)
    published_at = datetime(2026, 6, 11, 12, tzinfo=UTC)
    async with session_factory() as session:
        session.add_all(
            [
                Source(
                    id=SOURCE_ID,
                    slug="pravda-e2e",
                    name="Українська правда",
                    source_type="media",
                    base_url="https://www.pravda.com.ua",
                    logo_path="/sources/pravda.svg",
                    language="uk",
                ),
                Article(
                    id=ARTICLE_ID,
                    source_id=SOURCE_ID,
                    url="https://www.pravda.com.ua/news/e2e",
                    identity_url="https://www.pravda.com.ua/news/e2e",
                    title="Джерельний матеріал для перевірки",
                    published_at=published_at,
                    remote_image_url=None,
                ),
                Case(
                    id=CASE_ID,
                    slug="e2e-public-case",
                    title_uk="Корупційна справа для перевірки",
                    summary_uk="Детерміноване публічне досьє для браузерних перевірок.",
                    status="active",
                    first_seen_at=published_at,
                    last_updated_at=published_at,
                    article_count=1,
                    event_count=1,
                ),
                CaseArticle(case_id=CASE_ID, article_id=ARTICLE_ID),
                Entity(
                    id=ENTITY_ID,
                    slug="e2e-public-person",
                    entity_type="person",
                    canonical_name_uk="Тестова особа",
                    aliases=[],
                    description_uk="Особа для детермінованої браузерної перевірки.",
                ),
                ArticleEntity(
                    id=ARTICLE_ENTITY_ID,
                    article_id=ARTICLE_ID,
                    entity_id=ENTITY_ID,
                ),
                ArticleEntityCase(article_entity_id=ARTICLE_ENTITY_ID, case_id=CASE_ID),
                CaseEntity(
                    case_id=CASE_ID,
                    entity_id=ENTITY_ID,
                    first_article_id=ARTICLE_ID,
                    mention_count=1,
                ),
                Event(
                    id=EVENT_ID,
                    slug="e2e-public-event",
                    title_uk="Тестова подія",
                    description_uk="Подія з відкритим джерелом.",
                    event_year=2026,
                    event_month=6,
                    event_day=11,
                    event_date_precision="day",
                ),
                ArticleEvent(id=ARTICLE_EVENT_ID, article_id=ARTICLE_ID, event_id=EVENT_ID),
                ArticleEventCase(article_event_id=ARTICLE_EVENT_ID, case_id=CASE_ID),
                CaseEvent(
                    case_id=CASE_ID,
                    event_id=EVENT_ID,
                    first_article_id=ARTICLE_ID,
                    event_year=2026,
                    event_month=6,
                    event_day=11,
                    supporting_article_count=1,
                ),
            ]
        )
        await session.commit()
    await engine.dispose()


if __name__ == "__main__":
    run(seed())
