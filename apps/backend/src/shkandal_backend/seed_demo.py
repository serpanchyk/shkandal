"""Seed deterministic public data for local UI development and browser tests."""

from asyncio import run
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid5

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

SYNTHETIC_CASE_COUNT = 164
SYNTHETIC_ARTICLE_COUNT = 496
SYNTHETIC_EVENT_COUNT = 237
SYNTHETIC_ENTITY_COUNT = 88
SYNTHETIC_SOURCE_COUNT = 12
DEMO_IMAGE_URL = "https://tykyiv.com/media/6_ilulL7C.jpg"

THEMES = (
    ("закупівлі укриттів", "міських укриттів", "Київ"),
    ("відновлення мостів", "ремонту мостів", "Чернігів"),
    ("земельні аукціони", "комунальної землі", "Львів"),
    ("медичні закупівлі", "обладнання для лікарень", "Дніпро"),
    ("оборонні контракти", "постачання для військових частин", "Житомир"),
    ("відбудова шкіл", "реконструкції шкільних будівель", "Харків"),
    ("управління портом", "портової інфраструктури", "Одеса"),
    ("видобування піску", "користування надрами", "Полтава"),
    ("міський транспорт", "оновлення транспортного парку", "Запоріжжя"),
    ("енергетичні підряди", "ремонту енергетичних об’єктів", "Вінниця"),
    ("гуманітарна допомога", "розподілу гуманітарних вантажів", "Миколаїв"),
    ("лісові дозволи", "користування лісовими ресурсами", "Ужгород"),
    ("державна нерухомість", "оренди державних приміщень", "Івано-Франківськ"),
    ("цифровізація громади", "розробки муніципальних сервісів", "Тернопіль"),
    ("ремонт водогонів", "модернізації водопостачання", "Кропивницький"),
    ("будівництво житла", "програм доступного житла", "Рівне"),
    ("утилізація відходів", "перероблення побутових відходів", "Хмельницький"),
    ("закупівлі харчування", "постачання харчів до закладів", "Черкаси"),
    ("охорона пам’яток", "реставрації історичних будівель", "Чернівці"),
    ("управління грантами", "розподілу міжнародної допомоги", "Суми"),
    ("дорожні тендери", "ремонту регіональних доріг", "Луцьк"),
)

SOURCE_NAMES = (
    ("demo-hromada", "Громадський контроль", "ngo", "/sources/antac.png"),
    ("demo-nahliad", "Незалежний нагляд", "media", "/sources/bihus.png"),
    ("demo-suspilnyi-visnyk", "Суспільний вісник", "media", "/sources/suspilne.png"),
    ("demo-vidkryti-dani", "Відкриті дані", "ngo", "/sources/texty.png"),
    ("demo-miska-rada", "Міська рада", "government", "/sources/kmu.png"),
    ("demo-oblasna-prokuratura", "Обласна прокуратура", "law_enforcement", "/sources/gp.png"),
    ("demo-sudovyi-visnyk", "Судовий вісник", "court", "/sources/court-gov.png"),
    ("demo-derzhavna-sluzhba", "Державна служба", "institution", "/sources/rada.png"),
    ("demo-rehionalni-novyny", "Регіональні новини", "media", "/sources/hromadske.png"),
    ("demo-audyt", "Публічний аудит", "ngo", "/sources/chesno.png"),
    ("demo-rozsliduvannia", "Бюро розслідувань", "media", "/sources/radiosvoboda.png"),
    ("demo-dokumenty", "Офіційні документи", "institution", "/sources/arma.png"),
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
            rows = build_demo_rows()
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


def build_demo_rows() -> list[object]:
    """Build the complete deterministic graph without reading external data."""

    return [*_browser_fixture(), *_production_like_fixture(), *_synthetic_fixture()]


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
    return rows


def _synthetic_fixture() -> list[object]:
    """Return a dense fake graph with intentional cross-Case evidence overlap."""

    rows: list[object] = []
    source_ids = [_demo_uuid("source", index) for index in range(SYNTHETIC_SOURCE_COUNT)]
    article_ids = [_demo_uuid("article", index) for index in range(SYNTHETIC_ARTICLE_COUNT)]
    case_ids = [_demo_uuid("case", index) for index in range(SYNTHETIC_CASE_COUNT)]
    event_ids = [_demo_uuid("event", index) for index in range(SYNTHETIC_EVENT_COUNT)]
    entity_ids = [_demo_uuid("entity", index) for index in range(SYNTHETIC_ENTITY_COUNT)]
    base_date = datetime(2026, 6, 23, 18, tzinfo=UTC)

    for source_id, (slug, name, source_type, logo_path) in zip(
        source_ids, SOURCE_NAMES, strict=True
    ):
        rows.append(
            Source(
                id=source_id,
                slug=slug,
                name=name,
                source_type=source_type,
                base_url=f"https://example.com/{slug}",
                logo_path=logo_path,
                language="uk",
            )
        )

    for index, article_id in enumerate(article_ids):
        theme_name, subject, location = THEMES[(index // 24) % len(THEMES)]
        published_at = base_date - timedelta(hours=index * 5)
        article_url = f"https://example.com/demo/articles/{index + 1:03d}"
        rows.append(
            Article(
                id=article_id,
                source_id=source_ids[index % len(source_ids)],
                url=article_url,
                identity_url=article_url,
                title=_article_title(index, theme_name, subject, location),
                lead=(
                    f"Синтетичний матеріал про {subject}; створений лише для демонстрації "
                    "інтерфейсу Шкандалю."
                ),
                published_at=published_at,
                fetched_at=published_at + timedelta(minutes=10),
                source_language="uk",
                extracted_text=(
                    f"Демонстраційний текст №{index + 1} описує документи, рішення та реакції "
                    f"на перебіг справи про {subject} у місті {location}."
                ),
                remote_image_url=DEMO_IMAGE_URL if index >= 196 else None,
            )
        )

    case_article_indexes: dict[int, set[int]] = {
        case_index: set() for case_index in range(SYNTHETIC_CASE_COUNT)
    }
    for article_index in range(SYNTHETIC_ARTICLE_COUNT):
        primary_case = article_index % SYNTHETIC_CASE_COUNT
        case_article_indexes[primary_case].add(article_index)
        if article_index % 2 == 0:
            case_article_indexes[_theme_neighbor(primary_case, 1)].add(article_index)
        if article_index % 7 == 0:
            case_article_indexes[_theme_neighbor(primary_case, 2)].add(article_index)

    for case_index, case_id in enumerate(case_ids):
        theme_name, subject, location = THEMES[case_index // 8]
        linked_indexes = sorted(case_article_indexes[case_index])
        linked_dates = [
            base_date - timedelta(hours=article_index * 5) for article_index in linked_indexes
        ]
        rows.append(
            Case(
                id=case_id,
                slug=f"demo-case-{case_index + 1:03d}",
                title_uk=_case_title(case_index, theme_name, location),
                summary_uk=_case_summary(case_index, subject, location),
                status="active",
                first_seen_at=min(linked_dates),
                last_updated_at=max(linked_dates),
                article_count=len(linked_indexes),
                event_count=0,
            )
        )
        rows.extend(
            CaseArticle(
                case_id=case_id,
                article_id=article_ids[article_index],
                link_reason_uk="Матеріал містить документи або свідчення, пов’язані з досьє.",
            )
            for article_index in linked_indexes
        )

    event_case_indexes: dict[int, set[int]] = defaultdict(set)
    for event_index in range(SYNTHETIC_EVENT_COUNT):
        primary_case = event_index % SYNTHETIC_CASE_COUNT
        event_case_indexes[event_index].add(primary_case)
        event_case_indexes[event_index].add(_theme_neighbor(primary_case, 1 + event_index % 3))

    article_event_ids: dict[tuple[int, int], UUID] = {}
    event_count_by_case: dict[int, int] = defaultdict(int)
    for event_index, event_id in enumerate(event_ids):
        primary_case = event_index % SYNTHETIC_CASE_COUNT
        theme_name, subject, location = THEMES[primary_case // 8]
        event_date = base_date.date() - timedelta(days=event_index * 3)
        precision = ("day", "month", "year", "unknown")[event_index % 4]
        year = event_date.year if precision != "unknown" else None
        month = event_date.month if precision in {"day", "month"} else None
        day = event_date.day if precision == "day" else None
        rows.append(
            Event(
                id=event_id,
                slug=f"demo-event-{event_index + 1:03d}",
                title_uk=_event_title(event_index, theme_name, location),
                description_uk=(
                    f"У межах демонстраційної історії про {subject} зафіксовано новий "
                    "процесуальний або управлінський крок."
                ),
                event_year=year,
                event_month=month,
                event_day=day,
                event_date_precision=precision,
                location_uk=location if event_index % 5 else None,
            )
        )
        for case_index in sorted(event_case_indexes[event_index]):
            supporting_article_index = sorted(case_article_indexes[case_index])[
                event_index % len(case_article_indexes[case_index])
            ]
            pair = (supporting_article_index, event_index)
            article_event_id = article_event_ids.get(pair)
            if article_event_id is None:
                article_event_id = _demo_uuid(
                    "article-event", supporting_article_index * 1000 + event_index
                )
                article_event_ids[pair] = article_event_id
                rows.append(
                    ArticleEvent(
                        id=article_event_id,
                        article_id=article_ids[supporting_article_index],
                        event_id=event_id,
                    )
                )
            rows.extend(
                [
                    ArticleEventCase(
                        article_event_id=article_event_id,
                        case_id=case_ids[case_index],
                    ),
                    CaseEvent(
                        case_id=case_ids[case_index],
                        event_id=event_id,
                        first_article_id=article_ids[supporting_article_index],
                        event_year=year,
                        event_month=month,
                        event_day=day,
                        supporting_article_count=1,
                    ),
                ]
            )
            event_count_by_case[case_index] += 1

    for case_index, case_id in enumerate(case_ids):
        case_row = next(row for row in rows if isinstance(row, Case) and row.id == case_id)
        case_row.event_count = event_count_by_case[case_index]

    for entity_index, entity_id in enumerate(entity_ids):
        theme_index = min(entity_index // 4, len(THEMES) - 1)
        theme_name, subject, location = THEMES[theme_index]
        entity_type = (
            "person",
            "organization",
            "institution",
            "company",
            "political_party",
            "informal_group",
            "unknown_actor",
            "other",
        )[entity_index % 8]
        rows.append(
            Entity(
                id=entity_id,
                slug=f"demo-entity-{entity_index + 1:02d}",
                entity_type=entity_type,
                canonical_name_uk=_entity_name(entity_index, location),
                aliases=[f"Демонстраційна назва {entity_index + 1}"],
                description_uk=(
                    f"Вигадана сутність у матеріалах про {subject}. Не позначає реальну "
                    "особу, установу чи компанію."
                ),
            )
        )

    article_entity_ids: dict[tuple[int, int], UUID] = {}
    for case_index, case_id in enumerate(case_ids):
        theme_index = case_index // 8
        entity_indexes = {
            theme_index * 4 + case_index % 4,
            theme_index * 4 + (case_index + 1) % 4,
            84 + case_index % 4,
        }
        linked_articles = sorted(case_article_indexes[case_index])
        for entity_offset, entity_index in enumerate(sorted(entity_indexes)):
            mention_articles = linked_articles[: 1 + (case_index + entity_offset) % 2]
            for article_index in mention_articles:
                pair = (article_index, entity_index)
                article_entity_id = article_entity_ids.get(pair)
                if article_entity_id is None:
                    article_entity_id = _demo_uuid(
                        "article-entity", article_index * 1000 + entity_index
                    )
                    article_entity_ids[pair] = article_entity_id
                    rows.append(
                        ArticleEntity(
                            id=article_entity_id,
                            article_id=article_ids[article_index],
                            entity_id=entity_ids[entity_index],
                            role_uk="Згадується у демонстраційному матеріалі.",
                        )
                    )
                rows.append(ArticleEntityCase(article_entity_id=article_entity_id, case_id=case_id))
            rows.append(
                CaseEntity(
                    case_id=case_id,
                    entity_id=entity_ids[entity_index],
                    first_article_id=article_ids[mention_articles[0]],
                    mention_count=len(mention_articles),
                )
            )

    return rows


def _demo_uuid(kind: str, index: int) -> UUID:
    return uuid5(NAMESPACE_URL, f"https://shkandal.local/demo/{kind}/{index}")


def _theme_neighbor(case_index: int, offset: int) -> int:
    theme_start = (case_index // 8) * 8
    theme_size = min(8, SYNTHETIC_CASE_COUNT - theme_start)
    return theme_start + ((case_index - theme_start + offset) % theme_size)


def _case_title(index: int, theme_name: str, location: str) -> str:
    patterns = (
        "Перевірка рішень щодо теми «{theme}» у місті {location}",
        "Договори та можливий конфлікт інтересів: {theme}",
        "Як змінювалися умови проєкту «{theme}»",
        "Аудит витрат і підрядників у справі про {theme}",
    )
    return patterns[index % len(patterns)].format(theme=theme_name, location=location)


def _case_summary(index: int, subject: str, location: str) -> str:
    actions = (
        "журналісти зіставили тендерні документи, рішення посадовців і відповіді установ",
        "аудитори перевірили договори, зміни кошторису та зв’язки між підрядниками",
        "громадські організації проаналізували відкриті дані й звернулися по пояснення",
        "правоохоронці повідомили про перевірку обставин, викладених у публікаціях",
    )
    return (
        f"Вигадане демонстраційне досьє про {subject} у місті {location}. "
        f"У цій версії історії {actions[index % len(actions)]}. Усі назви та події "
        "створені для перевірки інтерфейсу."
    )


def _article_title(index: int, theme_name: str, subject: str, location: str) -> str:
    patterns = (
        "{location}: оприлюднено нові документи щодо теми «{theme}»",
        "Аудитори поставили запитання про вартість {subject}",
        "Підрядник відповів на зауваження до проєкту «{theme}»",
        "Рада переглянула рішення у справі про {subject}",
        "Розслідувачі зіставили договори та платежі: {theme}",
        "Суд розглянув клопотання у демонстраційній справі про {subject}",
    )
    return patterns[index % len(patterns)].format(
        theme=theme_name, subject=subject, location=location
    )


def _event_title(index: int, theme_name: str, location: str) -> str:
    patterns = (
        "Оприлюднено перший договір щодо теми «{theme}»",
        "Аудитори розпочали перевірку документів",
        "Замовник змінив умови закупівлі",
        "Підрядник надав публічне пояснення",
        "Суд призначив розгляд матеріалів",
        "У {location} представили результати перевірки",
    )
    return patterns[index % len(patterns)].format(theme=theme_name, location=location)


def _entity_name(index: int, location: str) -> str:
    names = (
        "Олексій Демченко",
        "Марія Коваль",
        "Громадська рада контролю",
        "Департамент міських проєктів",
        "ТОВ «Відкрита інфраструктура»",
        "Комісія з перевірки договорів",
        "Невстановлена група посередників",
        "Координаційний офіс відновлення",
    )
    return f"{names[index % len(names)]} — {location} {index // len(names) + 1}"


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
