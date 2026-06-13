"""Article-scoped global Entity and Event identity resolution."""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

from shkandal_database.jobs import ClaimedJob
from shkandal_database.models import (
    Article,
    ArticleCard,
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
)
from shkandal_vector_store.schemas import EntityVectorPayload, EventVectorPayload
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from worker_ml.article_cards import get_case_candidate_card
from worker_ml.case_resolution import _case_payload
from worker_ml.llm.contracts import (
    EntityResolutionDecision,
    EntityResolutionOutput,
    EventResolutionDecision,
    EventResolutionOutput,
)
from worker_ml.llm.runner import LlmTaskRunner
from worker_ml.vector_index import VectorIndexService

ENTITY_MUTATION_ADVISORY_LOCK = 7_214_801_902
EVENT_MUTATION_ADVISORY_LOCK = 7_214_801_903
MAX_IDENTITY_CANDIDATES = 8


class IdentityMutationBusyError(RuntimeError):
    """Another worker currently owns an identity namespace mutation."""


class ArticleEntityResolutionJobHandler:
    """Resolve all provisional entities from one article."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        runner: LlmTaskRunner,
        vector_index: VectorIndexService,
        *,
        model_name: str,
    ) -> None:
        self._session_factory = session_factory
        self._runner = runner
        self._vector_index = vector_index
        self._model_name = model_name

    async def handle(self, job: ClaimedJob) -> EntityResolutionOutput | None:
        if job.article_id is None:
            raise ValueError("entity resolution job requires article_id")
        async with self._session_factory() as session:
            if not await _try_lock(session, ENTITY_MUTATION_ADVISORY_LOCK):
                raise IdentityMutationBusyError("Entity mutation lock is busy")
            card, cases = await _load_card_and_cases(session, job.article_id)
            if card is None:
                return None
            case_ids = {case.id for case in cases}
            provisional = _with_provisional_refs(card.card_json.get("entities", []), "entity")
            if not provisional:
                return None
            retrieval_started_at = time.monotonic()
            candidates = await self._load_candidates(session, provisional)
            retrieval_duration_seconds = time.monotonic() - retrieval_started_at
            result = await self._runner.run_with_provenance(
                run_type="entity_resolution",
                model_name=self._model_name,
                variables={
                    "resolution_json": _resolution_json(provisional, candidates, cases),
                    "schema_json": json.dumps(
                        EntityResolutionOutput.model_json_schema(), ensure_ascii=False
                    ),
                },
                metadata={
                    "article_id": str(job.article_id),
                    "job_id": str(job.id),
                    "retrieval_duration_seconds": round(retrieval_duration_seconds, 6),
                },
            )
            output = cast(EntityResolutionOutput, result.output)
            _validate_coverage(provisional, output.entities, case_ids)
            candidate_ids = {
                item["provisional_ref"]: {candidate["entity_id"] for candidate in item_candidates}
                for item, item_candidates in zip(provisional, candidates, strict=True)
            }
            output = _normalize_invalid_entity_links(provisional, output, candidate_ids)
            affected = await _persist_entities(
                session,
                article_id=job.article_id,
                provisional=provisional,
                output=output,
                run_id=result.run_id,
                candidate_ids=candidate_ids,
            )
            await _rebuild_case_entities(session, affected)
            for entity_id in {entity_id for _, entity_id in affected}:
                entity = await session.get(Entity, entity_id)
                if entity is not None:
                    await self._vector_index.upsert_entity(entity.id, _entity_payload(entity))
            await session.commit()
            return output

    async def _load_candidates(
        self, session: AsyncSession, provisional: list[dict[str, Any]]
    ) -> list[list[dict[str, Any]]]:
        result_groups = await self._vector_index.search_entities_batch(
            [_entity_query(item) for item in provisional],
            limit=MAX_IDENTITY_CANDIDATES,
        )
        candidate_ids = {result.id for group in result_groups for result in group}
        rows = list(
            (await session.scalars(select(Entity).where(Entity.id.in_(candidate_ids)))).all()
        )
        by_id = {row.id: row for row in rows}
        return [
            [
                {
                    "entity_id": str(result.id),
                    "score": result.score,
                    **_entity_payload(by_id[result.id]).model_dump(mode="json"),
                }
                for result in results
                if result.id in by_id
            ]
            for results in result_groups
        ]


class ArticleEventResolutionJobHandler:
    """Resolve all provisional events from one article."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        runner: LlmTaskRunner,
        vector_index: VectorIndexService,
        *,
        model_name: str,
    ) -> None:
        self._session_factory = session_factory
        self._runner = runner
        self._vector_index = vector_index
        self._model_name = model_name

    async def handle(self, job: ClaimedJob) -> EventResolutionOutput | None:
        if job.article_id is None:
            raise ValueError("event resolution job requires article_id")
        async with self._session_factory() as session:
            if not await _try_lock(session, EVENT_MUTATION_ADVISORY_LOCK):
                raise IdentityMutationBusyError("Event mutation lock is busy")
            card, cases = await _load_card_and_cases(session, job.article_id)
            if card is None:
                return None
            case_ids = {case.id for case in cases}
            provisional = _with_provisional_refs(card.card_json.get("events", []), "event")
            if not provisional:
                return None
            retrieval_started_at = time.monotonic()
            candidates = await self._load_candidates(session, provisional)
            retrieval_duration_seconds = time.monotonic() - retrieval_started_at
            result = await self._runner.run_with_provenance(
                run_type="event_resolution",
                model_name=self._model_name,
                variables={
                    "resolution_json": _resolution_json(provisional, candidates, cases),
                    "schema_json": json.dumps(
                        EventResolutionOutput.model_json_schema(), ensure_ascii=False
                    ),
                },
                metadata={
                    "article_id": str(job.article_id),
                    "job_id": str(job.id),
                    "retrieval_duration_seconds": round(retrieval_duration_seconds, 6),
                },
            )
            output = cast(EventResolutionOutput, result.output)
            _validate_coverage(provisional, output.events, case_ids)
            candidate_ids = {
                item["provisional_ref"]: {candidate["event_id"] for candidate in item_candidates}
                for item, item_candidates in zip(provisional, candidates, strict=True)
            }
            output = _normalize_invalid_event_links(provisional, output, candidate_ids)
            output = _normalize_event_link_anchors(provisional, output, candidates)
            affected = await _persist_events(
                session,
                article_id=job.article_id,
                provisional=provisional,
                output=output,
                run_id=result.run_id,
                candidate_ids=candidate_ids,
            )
            await _rebuild_case_events(session, affected)
            for event_id in {event_id for _, event_id in affected}:
                event = await session.get(Event, event_id)
                if event is not None:
                    await self._vector_index.upsert_event(event.id, _event_payload(event))
            for case_id in {case_id for case_id, _ in affected}:
                case = await session.get(Case, case_id)
                if case is not None:
                    await self._vector_index.upsert_case(case.id, _case_payload(case))
            await session.commit()
            return output

    async def _load_candidates(
        self, session: AsyncSession, provisional: list[dict[str, Any]]
    ) -> list[list[dict[str, Any]]]:
        result_groups = await self._vector_index.search_events_batch(
            [_event_query(item) for item in provisional],
            limit=MAX_IDENTITY_CANDIDATES,
        )
        candidate_ids = {result.id for group in result_groups for result in group}
        rows = list((await session.scalars(select(Event).where(Event.id.in_(candidate_ids)))).all())
        by_id = {row.id: row for row in rows}
        return [
            [
                {
                    "event_id": str(result.id),
                    "score": result.score,
                    **_event_payload(by_id[result.id]).model_dump(mode="json"),
                }
                for result in results
                if result.id in by_id
            ]
            for results in result_groups
        ]


async def _load_card_and_cases(
    session: AsyncSession, article_id: UUID
) -> tuple[ArticleCard | None, list[Case]]:
    card = await get_case_candidate_card(session, article_id=article_id)
    if card is None:
        return None, []
    query = select(CaseArticle.case_id).where(CaseArticle.article_id == article_id)
    case_ids = set((await session.scalars(query)).all())
    if not case_ids:
        raise ValueError("identity resolution requires article Case links")
    cases = list((await session.scalars(select(Case).where(Case.id.in_(case_ids)))).all())
    if len(cases) != len(case_ids):
        raise ValueError("identity resolution found missing linked Cases")
    return card, cases


def _validate_coverage(
    provisional: list[dict[str, Any]],
    decisions: Sequence[EntityResolutionDecision | EventResolutionDecision],
    case_ids: set[UUID],
) -> None:
    expected = {str(item["provisional_ref"]) for item in provisional}
    actual = {decision.provisional_ref for decision in decisions}
    if actual != expected:
        raise ValueError("resolution decisions must exactly cover provisional refs")
    allowed = {str(case_id) for case_id in case_ids}
    for decision in decisions:
        if any(assignment.case_id not in allowed for assignment in decision.case_assignments):
            raise ValueError("resolution assigned an item to an unlinked Case")


def _normalize_invalid_entity_links(
    provisional: list[dict[str, Any]],
    output: EntityResolutionOutput,
    candidate_ids: dict[str, set[str]],
) -> EntityResolutionOutput:
    """Create a source-grounded Entity instead of merging an invalid identity."""

    by_ref = {str(item["provisional_ref"]): item for item in provisional}
    decisions = []
    for decision in output.entities:
        if decision.action in {"create_new", "reject"}:
            decisions.append(decision)
            continue
        if decision.existing_entity_id in candidate_ids[decision.provisional_ref]:
            decisions.append(decision)
            continue
        item = by_ref[decision.provisional_ref]
        decisions.append(
            decision.model_copy(
                update={
                    "action": "create_new",
                    "existing_entity_id": None,
                    "new_canonical_name_uk": str(item["name_uk"]),
                    "entity_type": str(item["entity_type"]),
                    "aliases": list(item.get("aliases", [])),
                    "description_uk": str(item["description_uk"]),
                }
            )
        )
    return EntityResolutionOutput(entities=decisions)


def _normalize_invalid_event_links(
    provisional: list[dict[str, Any]],
    output: EventResolutionOutput,
    candidate_ids: dict[str, set[str]],
) -> EventResolutionOutput:
    """Create a source-grounded Event instead of merging an invalid identity."""

    by_ref = {str(item["provisional_ref"]): item for item in provisional}
    decisions = []
    for decision in output.events:
        if decision.action in {"create_new", "reject"}:
            decisions.append(decision)
            continue
        if decision.existing_event_id in candidate_ids[decision.provisional_ref]:
            decisions.append(decision)
            continue
        decisions.append(_source_grounded_event_create(decision, by_ref[decision.provisional_ref]))
    return EventResolutionOutput(events=decisions)


def _normalize_event_link_anchors(
    provisional: list[dict[str, Any]],
    output: EventResolutionOutput,
    candidates: list[list[dict[str, Any]]],
) -> EventResolutionOutput:
    """Ground linked Event anchors in source evidence and reject conflicting merges."""

    by_ref = {str(item["provisional_ref"]): item for item in provisional}
    candidates_by_ref = {
        str(item["provisional_ref"]): {
            str(candidate["event_id"]): candidate for candidate in item_candidates
        }
        for item, item_candidates in zip(provisional, candidates, strict=True)
    }
    accepted_anchors: dict[str, dict[str, Any]] = {}
    decisions = []
    for decision in output.events:
        if decision.action != "link_existing":
            decisions.append(decision)
            continue
        item = by_ref[decision.provisional_ref]
        event_date = item.get("event_date")
        precision = str(item.get("event_date_precision", "unknown"))
        location = item.get("location_uk")
        year, month, day = _date_parts(event_date, precision)
        candidate = candidates_by_ref[decision.provisional_ref].get(str(decision.existing_event_id))
        event_id = str(decision.existing_event_id)
        anchors = accepted_anchors.get(event_id, candidate)
        if anchors is not None and (
            _event_date_conflicts(anchors, year, month, day)
            or _event_location_conflicts(anchors, location)
        ):
            decisions.append(_source_grounded_event_create(decision, item))
            continue
        accepted_anchors[event_id] = _merge_event_anchors(anchors, year, month, day, location)
        decisions.append(
            decision.model_copy(
                update={
                    "event_date": event_date,
                    "event_date_precision": precision,
                    "location_uk": location,
                }
            )
        )
    return EventResolutionOutput(events=decisions)


def _merge_event_anchors(
    current: dict[str, Any] | None,
    year: int | None,
    month: int | None,
    day: int | None,
    location: Any,
) -> dict[str, Any]:
    anchors = dict(current or {})
    anchors["event_year"] = anchors.get("event_year") or year
    anchors["event_month"] = anchors.get("event_month") or month
    anchors["event_day"] = anchors.get("event_day") or day
    anchors["location_uk"] = anchors.get("location_uk") or location
    return anchors


def _source_grounded_event_create(
    decision: EventResolutionDecision, item: dict[str, Any]
) -> EventResolutionDecision:
    return decision.model_copy(
        update={
            "action": "create_new",
            "existing_event_id": None,
            "new_title_uk": str(item["title_uk"]),
            "description_uk": str(item["description_uk"]),
            "event_date": item.get("event_date"),
            "event_date_precision": item.get("event_date_precision", "unknown"),
            "location_uk": item.get("location_uk"),
        }
    )


def _event_date_conflicts(
    candidate: dict[str, Any],
    year: int | None,
    month: int | None,
    day: int | None,
) -> bool:
    incoming = (year, month, day)
    current = (
        candidate.get("event_year"),
        candidate.get("event_month"),
        candidate.get("event_day"),
    )
    return any(
        current_part is not None and incoming_part is not None and current_part != incoming_part
        for current_part, incoming_part in zip(current, incoming, strict=True)
    )


def _event_location_conflicts(candidate: dict[str, Any], location: Any) -> bool:
    current = candidate.get("location_uk")
    return (
        isinstance(current, str)
        and isinstance(location, str)
        and current.casefold() != location.casefold()
    )


async def _persist_entities(
    session: AsyncSession,
    *,
    article_id: UUID,
    provisional: list[dict[str, Any]],
    output: EntityResolutionOutput,
    run_id: UUID | None,
    candidate_ids: dict[str, set[str]],
) -> set[tuple[UUID, UUID]]:
    old_rows = (
        await session.execute(
            select(ArticleEntityCase.case_id, ArticleEntity.entity_id)
            .join(ArticleEntity, ArticleEntity.id == ArticleEntityCase.article_entity_id)
            .where(ArticleEntity.article_id == article_id)
        )
    ).all()
    old_pairs: set[tuple[UUID, UUID]] = set((case_id, entity_id) for case_id, entity_id in old_rows)
    await session.execute(delete(ArticleEntity).where(ArticleEntity.article_id == article_id))
    await session.flush()
    by_ref = {str(item["provisional_ref"]): item for item in provisional}
    grouped: dict[UUID, dict[str, Any]] = {}
    for decision in output.entities:
        if decision.action == "reject":
            continue
        entity = await _resolve_entity(session, decision, candidate_ids[decision.provisional_ref])
        item = by_ref[decision.provisional_ref]
        entry = grouped.setdefault(entity.id, {"entity": entity, "items": [], "decisions": []})
        entry["items"].append(item)
        entry["decisions"].append(decision)
    new_pairs: set[tuple[UUID, UUID]] = set()
    for entity_id, group in grouped.items():
        decisions = cast(list[EntityResolutionDecision], group["decisions"])
        article_entity = ArticleEntity(
            article_id=article_id,
            entity_id=entity_id,
            llm_run_id=run_id,
            role_uk="; ".join(
                dict.fromkeys(str(item["description_uk"]) for item in group["items"])
            ),
            confidence=max(Decimal(str(decision.confidence)) for decision in decisions),
        )
        session.add(article_entity)
        await session.flush()
        assignments = _merged_assignments(decisions)
        for case_id, reason in assignments.items():
            parsed_case_id = UUID(case_id)
            session.add(
                ArticleEntityCase(
                    article_entity_id=article_entity.id,
                    case_id=parsed_case_id,
                    llm_run_id=run_id,
                    relevance_reason_uk=reason,
                )
            )
            new_pairs.add((parsed_case_id, entity_id))
    return old_pairs | new_pairs


async def _resolve_entity(
    session: AsyncSession, decision: EntityResolutionDecision, candidate_ids: set[str]
) -> Entity:
    if decision.action == "create_new":
        new_entity = Entity(
            id=uuid4(),
            slug=f"entity-{uuid4().hex}",
            entity_type=cast(str, decision.entity_type),
            canonical_name_uk=cast(str, decision.new_canonical_name_uk),
            aliases=list(dict.fromkeys(decision.aliases)),
            description_uk=decision.description_uk,
        )
        session.add(new_entity)
        await session.flush()
        return new_entity
    if decision.existing_entity_id not in candidate_ids:
        raise ValueError("entity decision references non-candidate identity")
    existing_entity = await session.get(Entity, UUID(decision.existing_entity_id))
    if existing_entity is None:
        raise ValueError("entity candidate disappeared")
    existing_entity.aliases = list(dict.fromkeys([*existing_entity.aliases, *decision.aliases]))
    if existing_entity.description_uk is None:
        existing_entity.description_uk = decision.description_uk
    if decision.action == "rename_existing":
        existing_entity.aliases = list(
            dict.fromkeys([*existing_entity.aliases, existing_entity.canonical_name_uk])
        )
        existing_entity.canonical_name_uk = cast(str, decision.new_canonical_name_uk)
    elif decision.action == "retype_existing":
        existing_entity.entity_type = cast(str, decision.entity_type)
    return existing_entity


async def _persist_events(
    session: AsyncSession,
    *,
    article_id: UUID,
    provisional: list[dict[str, Any]],
    output: EventResolutionOutput,
    run_id: UUID | None,
    candidate_ids: dict[str, set[str]],
) -> set[tuple[UUID, UUID]]:
    old_rows = (
        await session.execute(
            select(ArticleEventCase.case_id, ArticleEvent.event_id)
            .join(ArticleEvent, ArticleEvent.id == ArticleEventCase.article_event_id)
            .where(ArticleEvent.article_id == article_id)
        )
    ).all()
    old_pairs: set[tuple[UUID, UUID]] = set((case_id, event_id) for case_id, event_id in old_rows)
    await session.execute(delete(ArticleEvent).where(ArticleEvent.article_id == article_id))
    await session.flush()
    grouped: dict[UUID, list[EventResolutionDecision]] = {}
    for decision in output.events:
        if decision.action == "reject":
            continue
        event = await _resolve_event(session, decision, candidate_ids[decision.provisional_ref])
        grouped.setdefault(event.id, []).append(decision)
    new_pairs: set[tuple[UUID, UUID]] = set()
    for event_id, decisions in grouped.items():
        article_event = ArticleEvent(
            article_id=article_id,
            event_id=event_id,
            llm_run_id=run_id,
            confidence=max(Decimal(str(decision.confidence)) for decision in decisions),
        )
        session.add(article_event)
        await session.flush()
        for case_id, reason in _merged_assignments(decisions).items():
            parsed_case_id = UUID(case_id)
            session.add(
                ArticleEventCase(
                    article_event_id=article_event.id,
                    case_id=parsed_case_id,
                    llm_run_id=run_id,
                    relevance_reason_uk=reason,
                )
            )
            new_pairs.add((parsed_case_id, event_id))
    return old_pairs | new_pairs


async def _resolve_event(
    session: AsyncSession, decision: EventResolutionDecision, candidate_ids: set[str]
) -> Event:
    year, month, day = _date_parts(decision.event_date, decision.event_date_precision)
    if decision.action == "create_new":
        new_event = Event(
            id=uuid4(),
            slug=f"event-{uuid4().hex}",
            title_uk=cast(str, decision.new_title_uk),
            description_uk=decision.description_uk,
            event_year=year,
            event_month=month,
            event_day=day,
            event_date_precision=decision.event_date_precision,
            location_uk=decision.location_uk,
        )
        session.add(new_event)
        await session.flush()
        return new_event
    if decision.existing_event_id not in candidate_ids:
        raise ValueError("event decision references non-candidate identity")
    existing_event = await session.get(Event, UUID(decision.existing_event_id))
    if existing_event is None:
        raise ValueError("event candidate disappeared")
    if existing_event.description_uk is None:
        existing_event.description_uk = decision.description_uk
    _enrich_event_date(existing_event, year, month, day, decision.event_date_precision)
    if existing_event.location_uk is not None and decision.location_uk is not None:
        if existing_event.location_uk.casefold() != decision.location_uk.casefold():
            raise ValueError("event decision conflicts with existing location")
    elif existing_event.location_uk is None:
        existing_event.location_uk = decision.location_uk
    return existing_event


def _merged_assignments(
    decisions: Sequence[EntityResolutionDecision | EventResolutionDecision],
) -> dict[str, str]:
    merged: dict[str, str] = {}
    for decision in decisions:
        for assignment in decision.case_assignments:
            merged.setdefault(assignment.case_id, assignment.relevance_reason_uk)
    return merged


async def _rebuild_case_entities(session: AsyncSession, pairs: set[tuple[UUID, UUID]]) -> None:
    for case_id, entity_id in pairs:
        rows = (
            (
                await session.execute(
                    select(ArticleEntity.article_id)
                    .join(
                        ArticleEntityCase, ArticleEntityCase.article_entity_id == ArticleEntity.id
                    )
                    .join(Article, Article.id == ArticleEntity.article_id)
                    .where(
                        ArticleEntityCase.case_id == case_id, ArticleEntity.entity_id == entity_id
                    )
                    .order_by(Article.published_at.asc().nulls_last(), Article.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            await session.execute(
                delete(CaseEntity).where(
                    CaseEntity.case_id == case_id, CaseEntity.entity_id == entity_id
                )
            )
            continue
        await session.execute(
            insert(CaseEntity)
            .values(
                case_id=case_id,
                entity_id=entity_id,
                first_article_id=rows[0],
                mention_count=len(rows),
            )
            .on_conflict_do_update(
                index_elements=[CaseEntity.case_id, CaseEntity.entity_id],
                set_={"first_article_id": rows[0], "mention_count": len(rows)},
            )
        )


async def _rebuild_case_events(session: AsyncSession, pairs: set[tuple[UUID, UUID]]) -> None:
    for case_id, event_id in pairs:
        rows = (
            (
                await session.execute(
                    select(ArticleEvent.article_id)
                    .join(ArticleEventCase, ArticleEventCase.article_event_id == ArticleEvent.id)
                    .join(Article, Article.id == ArticleEvent.article_id)
                    .where(ArticleEventCase.case_id == case_id, ArticleEvent.event_id == event_id)
                    .order_by(Article.published_at.asc().nulls_last(), Article.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            await session.execute(
                delete(CaseEvent).where(
                    CaseEvent.case_id == case_id, CaseEvent.event_id == event_id
                )
            )
            continue
        event = await session.get(Event, event_id)
        if event is None:
            continue
        await session.execute(
            insert(CaseEvent)
            .values(
                case_id=case_id,
                event_id=event_id,
                first_article_id=rows[0],
                event_year=event.event_year,
                event_month=event.event_month,
                event_day=event.event_day,
                supporting_article_count=len(rows),
            )
            .on_conflict_do_update(
                index_elements=[CaseEvent.case_id, CaseEvent.event_id],
                set_={
                    "first_article_id": rows[0],
                    "event_year": event.event_year,
                    "event_month": event.event_month,
                    "event_day": event.event_day,
                    "supporting_article_count": len(rows),
                },
            )
        )
    for case_id in {case_id for case_id, _ in pairs}:
        event_count = await session.scalar(
            select(func.count()).select_from(CaseEvent).where(CaseEvent.case_id == case_id)
        )
        await session.execute(
            update(Case).where(Case.id == case_id).values(event_count=event_count or 0)
        )


def _resolution_json(
    provisional: list[dict[str, Any]],
    candidates: list[list[dict[str, Any]]],
    cases: list[Case],
) -> str:
    payload = {
        "items": [
            {"provisional": item, "candidates": item_candidates}
            for item, item_candidates in zip(provisional, candidates, strict=True)
        ],
        "linked_cases": [
            {
                "case_id": str(case.id),
                "title_uk": case.title_uk,
                "summary_uk": case.summary_uk,
            }
            for case in sorted(cases, key=lambda item: item.id)
        ],
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _with_provisional_refs(items: list[dict[str, Any]], prefix: str) -> list[dict[str, Any]]:
    """Give pre-reference article cards deterministic refs during rollout."""

    return [
        {**item, "provisional_ref": item.get("provisional_ref") or f"{prefix}_{index}"}
        for index, item in enumerate(items, start=1)
    ]


def _entity_query(item: dict[str, Any]) -> str:
    values = [item.get("name_uk"), item.get("entity_type"), item.get("description_uk")]
    return "\n".join(str(value) for value in values if value)


def _event_query(item: dict[str, Any]) -> str:
    values = [
        item.get("title_uk"),
        item.get("description_uk"),
        item.get("event_date"),
        item.get("location_uk"),
    ]
    return "\n".join(str(value) for value in values if value)


def _date_parts(value: str | None, precision: str) -> tuple[int | None, int | None, int | None]:
    if value is None or precision == "unknown":
        return None, None, None
    parts = [int(part) for part in value.split("-")]
    return parts[0], parts[1] if len(parts) > 1 else None, parts[2] if len(parts) > 2 else None


def _enrich_event_date(
    event: Event,
    year: int | None,
    month: int | None,
    day: int | None,
    precision: str,
) -> None:
    """Fill compatible missing date anchors without rewriting known facts."""

    incoming = (year, month, day)
    current = (event.event_year, event.event_month, event.event_day)
    for current_part, incoming_part in zip(current, incoming, strict=True):
        if current_part is not None and incoming_part is not None and current_part != incoming_part:
            raise ValueError("event decision conflicts with existing date")
    if year is None:
        return
    event.event_year = event.event_year or year
    event.event_month = event.event_month or month
    event.event_day = event.event_day or day
    precision_rank = {"unknown": 0, "year": 1, "month": 2, "day": 3}
    if precision_rank[precision] > precision_rank[event.event_date_precision]:
        event.event_date_precision = precision


def _entity_payload(entity: Entity) -> EntityVectorPayload:
    return EntityVectorPayload(
        slug=entity.slug,
        entity_type=entity.entity_type,
        canonical_name_uk=entity.canonical_name_uk,
        aliases=entity.aliases,
        description_uk=entity.description_uk,
        metadata=entity.metadata_,
    )


def _event_payload(event: Event) -> EventVectorPayload:
    return EventVectorPayload(
        slug=event.slug,
        title_uk=event.title_uk,
        description_uk=event.description_uk,
        event_year=event.event_year,
        event_month=event.event_month,
        event_day=event.event_day,
        event_date_precision=event.event_date_precision,
        location_uk=event.location_uk,
        metadata=event.metadata_,
    )


async def _try_lock(session: AsyncSession, lock_id: int) -> bool:
    return bool(await session.scalar(select(func.pg_try_advisory_xact_lock(lock_id))))
