from unittest.mock import AsyncMock, MagicMock, Mock
from uuid import uuid4

import pytest
from shkandal_database.models import Entity, Event
from worker_ml.identities.decisions import (
    date_parts,
    enrich_event_date,
    merged_assignments,
    normalize_event_link_anchors,
    normalize_invalid_entity_links,
    normalize_invalid_event_links,
    validate_coverage,
    with_provisional_refs,
)
from worker_ml.identities.payloads import entity_vector_payload, event_vector_payload
from worker_ml.identities.resolution import (
    ArticleEntityResolutionJobHandler,
    ArticleEventResolutionJobHandler,
)
from worker_ml.llm.contracts import (
    EntityCaseAssignment,
    EntityResolutionDecision,
    EntityResolutionDiagnosis,
    EntityResolutionOutput,
    EventCaseAssignment,
    EventResolutionDecision,
    EventResolutionDiagnosis,
    EventResolutionOutput,
)
from worker_ml.retrieval.vector_index import VectorIndexService


def _entity_diagnosis(**changes: object) -> EntityResolutionDiagnosis:
    diagnosis: dict[str, object] = {
        "is_named_stable_actor": True,
        "material_case_ids": ["case-a"],
        "identity_match_evidence_uk": "Назва і контекст збігаються.",
        "identity_conflict_uk": None,
        "rejection_signal_uk": None,
    }
    diagnosis.update(changes)
    return EntityResolutionDiagnosis.model_validate(diagnosis)


def _event_diagnosis(**changes: object) -> EventResolutionDiagnosis:
    diagnosis: dict[str, object] = {
        "is_concrete_occurrence": True,
        "occurrence_core_uk": "Конкретна подія у справі.",
        "anchor_summary_uk": "Дія, учасники та дата збігаються.",
        "candidate_match_evidence_uk": "Це та сама occurrence.",
        "anchor_conflict_uk": None,
        "temporal_scope_check_uk": "Подія вже відбулася і не виходить за поточну дату.",
        "future_date_warning_uk": None,
        "material_case_ids": ["case-a"],
        "rejection_signal_uk": None,
    }
    diagnosis.update(changes)
    return EventResolutionDiagnosis.model_validate(diagnosis)


def test_rollout_refs_are_deterministic_and_preserve_existing_refs() -> None:
    items = [{"name_uk": "A"}, {"provisional_ref": "entity_b", "name_uk": "B"}]

    assert with_provisional_refs(items, "entity") == [
        {"provisional_ref": "entity_1", "name_uk": "A"},
        {"provisional_ref": "entity_b", "name_uk": "B"},
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler_type", "search_method", "provisional"),
    [
        (
            ArticleEntityResolutionJobHandler,
            "search_entities_batch",
            [{"provisional_ref": "entity_1", "canonical_name_uk": "Особа"}],
        ),
        (
            ArticleEventResolutionJobHandler,
            "search_events_batch",
            [{"provisional_ref": "event_1", "title_uk": "Подія"}],
        ),
    ],
)
async def test_identity_candidate_limit_is_forwarded_to_vector_search(
    handler_type: type[ArticleEntityResolutionJobHandler] | type[ArticleEventResolutionJobHandler],
    search_method: str,
    provisional: list[dict[str, str]],
) -> None:
    vector_index = Mock(spec=VectorIndexService)
    search = AsyncMock(return_value=[[]])
    setattr(vector_index, search_method, search)
    session = Mock()
    session.scalars = AsyncMock(return_value=MagicMock(all=lambda: []))
    handler = handler_type(
        Mock(),
        Mock(),
        vector_index,
        model_name="resolution-model",
        candidate_limit=6,
    )

    assert await handler._load_candidates(session, provisional) == [[]]

    search.assert_awaited_once()
    assert search.await_args is not None
    assert search.await_args.kwargs["limit"] == 6


def test_resolution_must_cover_every_provisional_ref() -> None:
    case_id = uuid4()
    decision = EntityResolutionDecision(
        provisional_ref="entity_a",
        diagnosis=_entity_diagnosis(
            is_named_stable_actor=False,
            material_case_ids=[],
            identity_match_evidence_uk=None,
            rejection_signal_uk="Не є стабільною названою сутністю.",
        ),
        action="reject",
        confidence=0.8,
        reason_uk="Не є сутністю.",
        rejection_reason="not_an_entity",
    )

    with pytest.raises(ValueError, match="exactly cover"):
        validate_coverage(
            [{"provisional_ref": "entity_a"}, {"provisional_ref": "entity_b"}],
            [decision],
            {case_id},
        )


def test_resolution_rejects_assignment_to_unlinked_case() -> None:
    decision = EventResolutionDecision(
        provisional_ref="event_a",
        diagnosis=_event_diagnosis(candidate_match_evidence_uk=None),
        action="create_new",
        new_title_uk="Подія",
        confidence=0.9,
        reason_uk="Конкретна подія.",
        case_assignments=[EventCaseAssignment(case_id=str(uuid4()), relevance_reason_uk="Причина")],
    )

    with pytest.raises(ValueError, match="unlinked Case"):
        validate_coverage([{"provisional_ref": "event_a"}], [decision], {uuid4()})


def test_invalid_entity_link_is_rejected() -> None:
    case_id = uuid4()
    output = EntityResolutionOutput(
        entities=[
            EntityResolutionDecision(
                provisional_ref="entity_a",
                diagnosis=_entity_diagnosis(),
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

    with pytest.raises(ValueError, match="non-candidate identity"):
        normalize_invalid_entity_links(
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


def test_invalid_event_link_is_rejected() -> None:
    case_id = uuid4()
    output = EventResolutionOutput(
        events=[
            EventResolutionDecision(
                provisional_ref="event_a",
                diagnosis=_event_diagnosis(),
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

    with pytest.raises(ValueError, match="non-candidate identity"):
        normalize_invalid_event_links(
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


def test_conflicting_event_date_link_becomes_source_grounded_create() -> None:
    case_id = uuid4()
    event_id = uuid4()
    output = EventResolutionOutput(
        events=[
            EventResolutionDecision(
                provisional_ref="event_a",
                diagnosis=_event_diagnosis(),
                action="link_existing",
                existing_event_id=str(event_id),
                event_date="2026-07",
                event_date_precision="month",
                date_evidence_text="У липні 2026 року.",
                confidence=0.9,
                reason_uk="Та сама подія.",
                case_assignments=[
                    EventCaseAssignment(case_id=str(case_id), relevance_reason_uk="Причина")
                ],
            )
        ]
    )

    normalized = normalize_event_link_anchors(
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
                diagnosis=_event_diagnosis(),
                action="link_existing",
                existing_event_id=str(event_id),
                event_date="2026-07",
                event_date_precision="month",
                date_evidence_text="У липні 2026 року.",
                confidence=0.9,
                reason_uk="Та сама подія.",
                case_assignments=[
                    EventCaseAssignment(case_id=str(case_id), relevance_reason_uk="Причина")
                ],
            )
        ]
    )

    normalized = normalize_event_link_anchors(
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
    assert decision.event_date is None
    assert decision.event_date_precision == "unknown"
    assert decision.date_evidence_text is None


def test_conflicting_links_to_same_event_become_separate_source_grounded_events() -> None:
    case_id = uuid4()
    event_id = uuid4()
    output = EventResolutionOutput(
        events=[
            EventResolutionDecision(
                provisional_ref=provisional_ref,
                diagnosis=_event_diagnosis(),
                action="link_existing",
                existing_event_id=str(event_id),
                event_date=f"2026-{'06' if provisional_ref == 'event_june' else '07'}",
                event_date_precision="month",
                date_evidence_text="Місяць прямо вказано у статті.",
                confidence=0.9,
                reason_uk="Та сама подія.",
                case_assignments=[
                    EventCaseAssignment(case_id=str(case_id), relevance_reason_uk="Причина")
                ],
            )
            for provisional_ref in ("event_june", "event_july")
        ]
    )
    provisional = [
        {
            "provisional_ref": "event_june",
            "title_uk": "Червнева подія",
            "description_uk": "Опис.",
            "event_date": "2026-06",
            "event_date_precision": "month",
        },
        {
            "provisional_ref": "event_july",
            "title_uk": "Липнева подія",
            "description_uk": "Опис.",
            "event_date": "2026-07",
            "event_date_precision": "month",
        },
    ]
    candidate = {
        "event_id": str(event_id),
        "event_year": 2026,
        "event_month": None,
        "event_day": None,
    }

    normalized = normalize_event_link_anchors(
        provisional,
        output,
        [[candidate], [candidate]],
    )

    assert normalized.events[0].action == "link_existing"
    assert normalized.events[1].action == "create_new"
    assert normalized.events[1].new_title_uk == "Липнева подія"


def test_duplicate_provisionals_merge_case_assignments() -> None:
    case_a, case_b = uuid4(), uuid4()
    decisions = [
        EntityResolutionDecision(
            provisional_ref=f"entity_{suffix}",
            diagnosis=_entity_diagnosis(),
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

    assert merged_assignments(decisions) == {
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
    assert date_parts(value, precision) == expected


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

    assert entity_vector_payload(entity).canonical_name_uk == "Особа"
    assert event_vector_payload(event).event_month == 6


def test_event_date_enrichment_refines_compatible_precision() -> None:
    event = Event(
        slug="event-a",
        title_uk="Подія",
        event_year=2026,
        event_date_precision="year",
    )

    enrich_event_date(event, 2026, 6, 10, "day")

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
        enrich_event_date(event, 2026, 7, None, "month")
