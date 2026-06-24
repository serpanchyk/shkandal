from collections import Counter, defaultdict
from uuid import UUID

from shkandal_backend.seed_demo import DEMO_IMAGE_URL, build_demo_rows
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


def test_demo_fixture_has_expected_dense_graph() -> None:
    rows = build_demo_rows()
    counts = Counter(type(row) for row in rows)

    assert counts[Source] == 16
    assert counts[Article] == 500
    assert counts[Case] == 167
    assert counts[Event] == 240
    assert counts[Entity] == 90

    articles = [row for row in rows if isinstance(row, Article)]
    assert sum(article.remote_image_url is None for article in articles) == 200
    assert sum(article.remote_image_url == DEMO_IMAGE_URL for article in articles) == 300


def test_demo_fixture_ids_slugs_urls_and_links_are_valid() -> None:
    rows = build_demo_rows()
    sources = [row for row in rows if isinstance(row, Source)]
    articles = [row for row in rows if isinstance(row, Article)]
    cases = [row for row in rows if isinstance(row, Case)]
    entities = [row for row in rows if isinstance(row, Entity)]
    events = [row for row in rows if isinstance(row, Event)]

    _assert_unique([row.id for row in sources])
    _assert_unique([row.id for row in articles])
    _assert_unique([row.id for row in cases])
    _assert_unique([row.id for row in entities])
    _assert_unique([row.id for row in events])
    _assert_unique([row.slug for row in sources])
    _assert_unique([row.slug for row in cases])
    _assert_unique([row.slug for row in entities])
    _assert_unique([row.slug for row in events])
    _assert_unique([row.identity_url for row in articles])

    source_ids = {row.id for row in sources}
    article_ids = {row.id for row in articles}
    case_ids = {row.id for row in cases}
    entity_ids = {row.id for row in entities}
    event_ids = {row.id for row in events}
    article_entity_ids = {row.id for row in rows if isinstance(row, ArticleEntity)}
    article_event_ids = {row.id for row in rows if isinstance(row, ArticleEvent)}

    assert all(article.source_id in source_ids for article in articles)
    assert all(
        row.case_id in case_ids and row.article_id in article_ids
        for row in rows
        if isinstance(row, CaseArticle)
    )
    assert all(
        row.article_id in article_ids and row.entity_id in entity_ids
        for row in rows
        if isinstance(row, ArticleEntity)
    )
    assert all(
        row.article_entity_id in article_entity_ids and row.case_id in case_ids
        for row in rows
        if isinstance(row, ArticleEntityCase)
    )
    assert all(
        row.article_id in article_ids and row.event_id in event_ids
        for row in rows
        if isinstance(row, ArticleEvent)
    )
    assert all(
        row.article_event_id in article_event_ids and row.case_id in case_ids
        for row in rows
        if isinstance(row, ArticleEventCase)
    )
    assert all(
        row.case_id in case_ids and row.entity_id in entity_ids
        for row in rows
        if isinstance(row, CaseEntity)
    )
    assert all(
        row.case_id in case_ids and row.event_id in event_ids
        for row in rows
        if isinstance(row, CaseEvent)
    )


def test_synthetic_cases_have_consistent_counts_and_related_cases() -> None:
    rows = build_demo_rows()
    cases = {
        row.id: row for row in rows if isinstance(row, Case) and row.slug.startswith("demo-case-")
    }
    article_ids_by_case: dict[UUID, set[UUID]] = defaultdict(set)
    event_ids_by_case: dict[UUID, set[UUID]] = defaultdict(set)
    entity_ids_by_case: dict[UUID, set[UUID]] = defaultdict(set)

    for row in rows:
        if isinstance(row, CaseArticle):
            article_ids_by_case[row.case_id].add(row.article_id)
        elif isinstance(row, CaseEvent):
            event_ids_by_case[row.case_id].add(row.event_id)
        elif isinstance(row, CaseEntity):
            entity_ids_by_case[row.case_id].add(row.entity_id)

    assert len(cases) == 164
    for case_id, case_row in cases.items():
        assert case_row.article_count == len(article_ids_by_case[case_id])
        assert case_row.event_count == len(event_ids_by_case[case_id])
        assert len(article_ids_by_case[case_id]) >= 3
        assert len(event_ids_by_case[case_id]) >= 1
        assert len(entity_ids_by_case[case_id]) == 3

    representative_id = next(
        case_id for case_id, case_row in cases.items() if case_row.slug == "demo-case-001"
    )
    related_ids = {
        other_id
        for other_id in cases
        if other_id != representative_id
        and (
            article_ids_by_case[representative_id] & article_ids_by_case[other_id]
            or event_ids_by_case[representative_id] & event_ids_by_case[other_id]
            or entity_ids_by_case[representative_id] & entity_ids_by_case[other_id]
        )
    }
    assert len(related_ids) >= 5


def _assert_unique(values: list[object]) -> None:
    assert len(values) == len(set(values))
