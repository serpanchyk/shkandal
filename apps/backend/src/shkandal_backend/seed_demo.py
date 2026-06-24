"""Seed deterministic public data for local UI development and browser tests."""

from asyncio import run
from datetime import UTC, datetime, timedelta
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
from sqlalchemy import select

SOURCE_ID = UUID("10000000-0000-0000-0000-000000000001")
ARTICLE_ID = UUID("20000000-0000-0000-0000-000000000001")
CASE_ID = UUID("30000000-0000-0000-0000-000000000001")
OTHER_CASE_ID = UUID("30000000-0000-0000-0000-000000000002")
ENTITY_ID = UUID("40000000-0000-0000-0000-000000000001")
EVENT_ID = UUID("50000000-0000-0000-0000-000000000001")
ARTICLE_ENTITY_ID = UUID("60000000-0000-0000-0000-000000000001")
ARTICLE_EVENT_ID = UUID("70000000-0000-0000-0000-000000000001")

DEMO_CASE_ID = UUID("80000000-0000-0000-0000-000000000001")
DEMO_ENTITY_ID = UUID("80000000-0000-0000-0000-000000000002")
DEMO_SOURCE_IDS = (
    UUID("81000000-0000-0000-0000-000000000001"),
    UUID("81000000-0000-0000-0000-000000000002"),
    UUID("81000000-0000-0000-0000-000000000003"),
)
DEMO_ARTICLE_IDS = (
    UUID("82000000-0000-0000-0000-000000000001"),
    UUID("82000000-0000-0000-0000-000000000002"),
    UUID("82000000-0000-0000-0000-000000000003"),
)
DEMO_EVENT_IDS = (
    UUID("83000000-0000-0000-0000-000000000001"),
    UUID("83000000-0000-0000-0000-000000000002"),
)
DEMO_ARTICLE_ENTITY_IDS = (
    UUID("84000000-0000-0000-0000-000000000001"),
    UUID("84000000-0000-0000-0000-000000000002"),
    UUID("84000000-0000-0000-0000-000000000003"),
)
DEMO_ARTICLE_EVENT_IDS = (
    UUID("85000000-0000-0000-0000-000000000001"),
    UUID("85000000-0000-0000-0000-000000000002"),
)


async def seed_demo() -> None:
    """Insert the committed sample graph once, preserving local view counts."""

    engine = create_async_engine_from_config(DatabaseConfig())
    session_factory = create_async_sessionmaker(engine)
    try:
        async with session_factory() as session:
            existing_case_id = await session.scalar(select(Case.id).where(Case.id == CASE_ID))
            if existing_case_id is not None:
                return
            rows = [*_browser_fixture(), *_production_like_fixture()]
            session.add_all(
                [row for row in rows if isinstance(row, Source | Article | Case | Entity | Event)]
            )
            await session.flush()
            session.add_all(
                [row for row in rows if isinstance(row, CaseArticle | ArticleEntity | ArticleEvent)]
            )
            await session.flush()
            session.add_all(
                [
                    row
                    for row in rows
                    if isinstance(
                        row,
                        ArticleEntityCase | ArticleEventCase | CaseEntity | CaseEvent,
                    )
                ]
            )
            await session.commit()
    finally:
        await engine.dispose()


def _browser_fixture() -> list[object]:
    published_at = datetime(2026, 6, 11, 12, tzinfo=UTC)
    rows: list[object] = [
        Source(
            id=SOURCE_ID,
            slug="pravda-e2e",
            name="Українська правда",
            source_type="media",
            base_url="https://www.pravda.com.ua",
            logo_path="/sources/pravda.png",
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
        Case(
            id=OTHER_CASE_ID,
            slug="e2e-other-case",
            title_uk="Інша справа зі спільним матеріалом",
            summary_uk="Досьє для перевірки похідної навігації між справами.",
            status="active",
            first_seen_at=published_at,
            last_updated_at=published_at - timedelta(minutes=1),
            article_count=1,
            event_count=0,
        ),
        CaseArticle(case_id=OTHER_CASE_ID, article_id=ARTICLE_ID),
        Entity(
            id=ENTITY_ID,
            slug="e2e-public-person",
            entity_type="person",
            canonical_name_uk="Тестова особа",
            aliases=[],
            description_uk="Особа для детермінованої браузерної перевірки.",
        ),
        ArticleEntity(id=ARTICLE_ENTITY_ID, article_id=ARTICLE_ID, entity_id=ENTITY_ID),
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
    for index in range(1, 165):
        article_id = UUID(f"21000000-0000-0000-0000-{index:012d}")
        case_id = UUID(f"31000000-0000-0000-0000-{index:012d}")
        supplemental_published_at = published_at - timedelta(hours=index)
        rows.extend(
            [
                Article(
                    id=article_id,
                    source_id=SOURCE_ID,
                    url=f"https://www.pravda.com.ua/news/e2e-feed-{index}",
                    identity_url=f"https://www.pravda.com.ua/news/e2e-feed-{index}",
                    title=f"Джерельний матеріал стрічки {index}",
                    published_at=supplemental_published_at,
                    remote_image_url=None,
                ),
                Case(
                    id=case_id,
                    slug=f"e2e-feed-case-{index:02d}",
                    title_uk=f"Публічне досьє стрічки {index:02d}",
                    summary_uk="Детермінована справа для перевірки композиції головної сторінки.",
                    status="active",
                    first_seen_at=supplemental_published_at,
                    last_updated_at=supplemental_published_at,
                    article_count=1,
                    event_count=0,
                ),
                CaseArticle(case_id=case_id, article_id=article_id),
            ]
        )
    return rows


def _production_like_fixture() -> list[object]:
    """Return a sanitized snapshot of one public dossier from the main database."""

    published_at = (
        datetime(2024, 4, 8, 16, 50, 50, tzinfo=UTC),
        datetime(2025, 8, 4, 8, 53, 6, tzinfo=UTC),
        datetime(2026, 6, 5, 15, 56, 57, tzinfo=UTC),
    )
    source_rows = (
        ("bihus-demo", "Bihus.Info", "https://bihus.info", "/sources/bihus.png"),
        (
            "slovoidilo-demo",
            "Слово і Діло",
            "https://www.slovoidilo.ua",
            "/sources/slovoidilo.png",
        ),
        ("babel-demo", "Бабель", "https://babel.ua", "/sources/babel.png"),
    )
    article_rows = (
        (
            "Ідентифікована частина російських суден і зернотрейдерів, що вивозили "
            "українське зерно через окупований порт Маріуполя - Bihus.Info",
            "https://bihus.info/identyfikovana-chastyna-rosijskyh-suden-i-zernotrejderiv-"
            "shho-vyvozyly-ukrayinske-zerno-cherez-okupovanyj-port-mariupolya/",
        ),
        (
            "Зеленський запровадив санкції проти викрадачів українських ресурсів з ТОТ",
            "https://www.slovoidilo.ua/2025/08/04/novyna/polityka/zelenskyj-zaprovadyv-"
            "sankcziyi-proty-vykradachiv-ukrayinskyx-resursiv-tot",
        ),
        (
            "Суд у Швеції дозволив передати Україні російське судно Caffa, яке "
            "підозрюють у перевезенні краденого зерна",
            "https://babel.ua/news/127536-sud-u-shveciji-dozvoliv-peredati-ukrajini-"
            "rosiyske-sudno-caffa-yake-pidozryuyut-u-perevezenni-kradenogo-zerna",
        ),
    )
    rows: list[object] = [
        *[
            Source(
                id=source_id,
                slug=slug,
                name=name,
                source_type="media",
                base_url=base_url,
                logo_path=logo_path,
                language="uk",
            )
            for source_id, (slug, name, base_url, logo_path) in zip(
                DEMO_SOURCE_IDS, source_rows, strict=True
            )
        ],
        *[
            Article(
                id=article_id,
                source_id=source_id,
                url=url,
                identity_url=url,
                title=title,
                published_at=article_published_at,
                remote_image_url=None,
            )
            for article_id, source_id, article_published_at, (title, url) in zip(
                DEMO_ARTICLE_IDS,
                DEMO_SOURCE_IDS,
                published_at,
                article_rows,
                strict=True,
            )
        ],
        Case(
            id=DEMO_CASE_ID,
            slug="demo-stolen-grain-caffa",
            title_uk=(
                "Незаконне вивезення українського зерна з окупованого Маріуполя та справа Caffa"
            ),
            summary_uk=(
                "Журналісти встановили, що російські судна вивозили українське зерно "
                "з окупованого Маріуполя. Україна запровадила санкції проти причетних "
                "осіб і компаній, а шведський суд дозволив передати Україні затримане "
                "судно Caffa."
            ),
            status="active",
            first_seen_at=published_at[0],
            last_updated_at=published_at[2],
            article_count=3,
            event_count=2,
        ),
        *[
            CaseArticle(case_id=DEMO_CASE_ID, article_id=article_id)
            for article_id in DEMO_ARTICLE_IDS
        ],
        Entity(
            id=DEMO_ENTITY_ID,
            slug="demo-caffa",
            entity_type="other",
            canonical_name_uk="Caffa",
            aliases=[],
            description_uk=(
                "Російське судно, затримане за підозрою у перевезенні краденого "
                "зерна з окупованих територій України."
            ),
        ),
        *[
            ArticleEntity(
                id=article_entity_id,
                article_id=article_id,
                entity_id=DEMO_ENTITY_ID,
            )
            for article_entity_id, article_id in zip(
                DEMO_ARTICLE_ENTITY_IDS, DEMO_ARTICLE_IDS, strict=True
            )
        ],
        *[
            ArticleEntityCase(article_entity_id=article_entity_id, case_id=DEMO_CASE_ID)
            for article_entity_id in DEMO_ARTICLE_ENTITY_IDS
        ],
        CaseEntity(
            case_id=DEMO_CASE_ID,
            entity_id=DEMO_ENTITY_ID,
            first_article_id=DEMO_ARTICLE_IDS[0],
            mention_count=3,
        ),
        Event(
            id=DEMO_EVENT_IDS[0],
            slug="demo-grain-loaded-in-mariupol",
            title_uk="Російські судна завантажували зерно в окупованому Маріуполі",
            description_uk=(
                "Щонайменше три російські судна були зафіксовані під час завантаження "
                "зерном в окупованому Маріуполі."
            ),
            event_year=2023,
            event_date_precision="year",
            location_uk="Маріуполь",
        ),
        Event(
            id=DEMO_EVENT_IDS[1],
            slug="demo-caffa-transfer-approved",
            title_uk="Шведський суд дозволив передати Україні судно Caffa",
            description_uk=(
                "Шведський суд визнав законним арешт судна Caffa та дозволив передати його Україні."
            ),
            event_year=2026,
            event_month=6,
            event_day=5,
            event_date_precision="day",
            location_uk="Балтійське море",
        ),
        ArticleEvent(
            id=DEMO_ARTICLE_EVENT_IDS[0],
            article_id=DEMO_ARTICLE_IDS[0],
            event_id=DEMO_EVENT_IDS[0],
        ),
        ArticleEvent(
            id=DEMO_ARTICLE_EVENT_IDS[1],
            article_id=DEMO_ARTICLE_IDS[2],
            event_id=DEMO_EVENT_IDS[1],
        ),
        ArticleEventCase(
            article_event_id=DEMO_ARTICLE_EVENT_IDS[0],
            case_id=DEMO_CASE_ID,
        ),
        ArticleEventCase(
            article_event_id=DEMO_ARTICLE_EVENT_IDS[1],
            case_id=DEMO_CASE_ID,
        ),
        CaseEvent(
            case_id=DEMO_CASE_ID,
            event_id=DEMO_EVENT_IDS[0],
            first_article_id=DEMO_ARTICLE_IDS[0],
            event_year=2023,
            supporting_article_count=1,
        ),
        CaseEvent(
            case_id=DEMO_CASE_ID,
            event_id=DEMO_EVENT_IDS[1],
            first_article_id=DEMO_ARTICLE_IDS[2],
            event_year=2026,
            event_month=6,
            event_day=5,
            supporting_article_count=1,
        ),
    ]
    return rows


if __name__ == "__main__":
    run(seed_demo())
