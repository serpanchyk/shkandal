from uuid import uuid4

import pytest
from shkandal_database.models import Entity, Event
from worker_ml.identity_resolution import (
    _date_parts,
    _enrich_event_date,
    _entity_payload,
    _event_payload,
    _merged_assignments,
    _normalize_event_link_anchors,
    _normalize_invalid_entity_links,
    _normalize_invalid_event_links,
    _validate_coverage,
    _with_provisional_refs,
)
from worker_ml.llm.contracts import (
    EntityCaseAssignment,
    EntityResolutionDecision,
    EntityResolutionOutput,
    EventCaseAssignment,
    EventResolutionDecision,
    EventResolutionOutput,
)


def test_rollout_refs_are_deterministic_and_preserve_existing_refs() -> None:
    items = [{"name_uk": "A"}, {"provisional_ref": "entity_b", "name_uk": "B"}]

    assert _with_provisional_refs(items, "entity") == [
        {"provisional_ref": "entity_1", "name_uk": "A"},
        {"provisional_ref": "entity_b", "name_uk": "B"},
    ]


def test_resolution_must_cover_every_provisional_ref() -> None:
    case_id = uuid4()
    decision = EntityResolutionDecision(
        provisional_ref="entity_a",
        action="reject",
        confidence=0.8,
        reason_uk="Не є сутністю.",
        rejection_reason="not_an_entity",
    )

    with pytest.raises(ValueError, match="exactly cover"):
        _validate_coverage(
            [{"provisional_ref": "entity_a"}, {"provisional_ref": "entity_b"}],
            [decision],
            {case_id},
        )


def test_resolution_rejects_assignment_to_unlinked_case() -> None:
    decision = EventResolutionDecision(
        provisional_ref="event_a",
        action="create_new",
        new_title_uk="Подія",
        confidence=0.9,
        reason_uk="Конкретна подія.",
        case_assignments=[EventCaseAssignment(case_id=str(uuid4()), relevance_reason_uk="Причина")],
    )

    with pytest.raises(ValueError, match="unlinked Case"):
        _validate_coverage([{"provisional_ref": "event_a"}], [decision], {uuid4()})


def test_invalid_entity_link_becomes_source_grounded_create() -> None:
    case_id = uuid4()
    output = EntityResolutionOutput(
        entities=[
            EntityResolutionDecision(
                provisional_ref="entity_a",
                action="link_existing",
                existing_entity_id=str(case_id),
                confidence=0.9,
                reason_uk="Та сама сутність.",
                case_assignments=[
                    EntityCaseAssignment(case_id=str(case_id), relevance_reason_uk="Причина")
                ],
            )
        ]
    )

    normalized = _normalize_invalid_entity_links(
        [
            {
                "provisional_ref": "entity_a",
                "name_uk": "Нова сутність",
                "entity_type": "institution",
                "aliases": ["НС"],
                "description_uk": "Опис.",
            }
        ],
        output,
        {"entity_a": set()},
    )

    decision = normalized.entities[0]
    assert decision.action == "create_new"
    assert decision.existing_entity_id is None
    assert decision.new_canonical_name_uk == "Нова сутність"
    assert decision.entity_type == "institution"


def test_invalid_event_link_becomes_source_grounded_create() -> None:
    case_id = uuid4()
    output = EventResolutionOutput(
        events=[
            EventResolutionDecision(
                provisional_ref="event_a",
                action="link_existing",
                existing_event_id=str(case_id),
                confidence=0.9,
                reason_uk="Та сама подія.",
                case_assignments=[
                    EventCaseAssignment(case_id=str(case_id), relevance_reason_uk="Причина")
                ],
            )
        ]
    )

    normalized = _normalize_invalid_event_links(
        [
            {
                "provisional_ref": "event_a",
                "title_uk": "Нова подія",
                "description_uk": "Опис.",
                "event_date": "2026-06",
                "event_date_precision": "month",
                "location_uk": "Київ",
            }
        ],
        output,
        {"event_a": set()},
    )

    decision = normalized.events[0]
    assert decision.action == "create_new"
    assert decision.existing_event_id is None
    assert decision.new_title_uk == "Нова подія"
    assert decision.event_date == "2026-06"


def test_conflicting_event_date_link_becomes_source_grounded_create() -> None:
    case_id = uuid4()
    event_id = uuid4()
    output = EventResolutionOutput(
        events=[
            EventResolutionDecision(
                provisional_ref="event_a",
                action="link_existing",
                existing_event_id=str(event_id),
                event_date="2026-07",
                event_date_precision="month",
                confidence=0.9,
                reason_uk="Та сама подія.",
                case_assignments=[
                    EventCaseAssignment(case_id=str(case_id), relevance_reason_uk="Причина")
                ],
            )
        ]
    )

    normalized = _normalize_event_link_anchors(
        [
            {
                "provisional_ref": "event_a",
                "title_uk": "Нова подія",
                "description_uk": "Опис.",
                "event_date": "2026-07",
                "event_date_precision": "month",
                "location_uk": "Київ",
            }
        ],
        output,
        [
            [
                {
                    "event_id": str(event_id),
                    "event_year": 2026,
                    "event_month": 6,
                    "event_day": None,
                }
            ]
        ],
    )

    decision = normalized.events[0]
    assert decision.action == "create_new"
    assert decision.existing_event_id is None
    assert decision.new_title_uk == "Нова подія"
    assert decision.event_date == "2026-07"


def test_event_link_anchors_are_source_grounded_before_persistence() -> None:
    case_id = uuid4()
    event_id = uuid4()
    output = EventResolutionOutput(
        events=[
            EventResolutionDecision(
                provisional_ref="event_a",
                action="link_existing",
                existing_event_id=str(event_id),
                event_date="2026-07",
                event_date_precision="month",
                confidence=0.9,
                reason_uk="Та сама подія.",
                case_assignments=[
                    EventCaseAssignment(case_id=str(case_id), relevance_reason_uk="Причина")
                ],
            )
        ]
    )

    normalized = _normalize_event_link_anchors(
        [
            {
                "provisional_ref": "event_a",
                "title_uk": "Відома подія",
                "description_uk": "Опис.",
                "event_date": "2026-06",
                "event_date_precision": "month",
            }
        ],
        output,
        [
            [
                {
                    "event_id": str(event_id),
                    "event_year": 2026,
                    "event_month": 6,
                    "event_day": None,
                }
            ]
        ],
    )

    decision = normalized.events[0]
    assert decision.action == "link_existing"
    assert decision.event_date == "2026-06"
    assert decision.event_date_precision == "month"


def test_duplicate_provisionals_merge_case_assignments() -> None:
    case_a, case_b = uuid4(), uuid4()
    decisions = [
        EntityResolutionDecision(
            provisional_ref=f"entity_{suffix}",
            action="link_existing",
            existing_entity_id=str(uuid4()),
            confidence=0.9,
            reason_uk="Та сама сутність.",
            case_assignments=[
                EntityCaseAssignment(case_id=str(case_id), relevance_reason_uk=reason)
            ],
        )
        for suffix, case_id, reason in (
            ("a", case_a, "Перша причина"),
            ("b", case_b, "Друга причина"),
        )
    ]

    assert _merged_assignments(decisions) == {
        str(case_a): "Перша причина",
        str(case_b): "Друга причина",
    }


@pytest.mark.parametrize(
    ("value", "precision", "expected"),
    [
        ("2026-06-10", "day", (2026, 6, 10)),
        ("2026-06", "month", (2026, 6, None)),
        ("2026", "year", (2026, None, None)),
        (None, "unknown", (None, None, None)),
    ],
)
def test_event_date_parts_preserve_real_precision(
    value: str | None, precision: str, expected: tuple[int | None, int | None, int | None]
) -> None:
    assert _date_parts(value, precision) == expected


def test_identity_payloads_are_rebuildable_from_postgres() -> None:
    entity = Entity(
        slug="entity-a",
        entity_type="person",
        canonical_name_uk="Особа",
        aliases=["Аліас"],
        description_uk="Опис",
        metadata_={"source": "test"},
    )
    event = Event(
        slug="event-a",
        title_uk="Подія",
        event_year=2026,
        event_month=6,
        event_day=None,
        event_date_precision="month",
        metadata_={"source": "test"},
    )

    assert _entity_payload(entity).canonical_name_uk == "Особа"
    assert _event_payload(event).event_month == 6


def test_event_date_enrichment_refines_compatible_precision() -> None:
    event = Event(
        slug="event-a",
        title_uk="Подія",
        event_year=2026,
        event_date_precision="year",
    )

    _enrich_event_date(event, 2026, 6, 10, "day")

    assert (event.event_year, event.event_month, event.event_day) == (2026, 6, 10)
    assert event.event_date_precision == "day"


def test_event_date_enrichment_rejects_conflicting_anchor() -> None:
    event = Event(
        slug="event-a",
        title_uk="Подія",
        event_year=2026,
        event_month=6,
        event_date_precision="month",
    )

    with pytest.raises(ValueError, match="conflicts"):
        _enrich_event_date(event, 2026, 7, None, "month")
