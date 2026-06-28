"""Article-scoped global Entity and Event identity resolution."""

from __future__ import annotations

import time
from datetime import datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from shkandal_database.jobs import ClaimedJob
from shkandal_database.models import (
    ArticleCard,
    ArticleEntity,
    ArticleEntityCase,
    ArticleEvent,
    ArticleEventCase,
    Case,
    CaseArticle,
    Entity,
    Event,
)
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from worker_ml.articles.cards import get_case_candidate_card
from worker_ml.cases.publication import (
    ENTITY_MUTATION_ADVISORY_LOCK,
    EVENT_MUTATION_ADVISORY_LOCK,
    case_vector_payload,
    rebuild_case_entities,
    rebuild_case_events,
    try_mutation_lock,
)
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
from worker_ml.identities.payloads import (
    entity_query,
    entity_vector_payload,
    event_query,
    event_vector_payload,
)
from worker_ml.llm.budgeting import json_dumps_compact, prompt_size_chars
from worker_ml.llm.contracts import (
    EntityResolutionDecision,
    EntityResolutionOutput,
    EventResolutionDecision,
    EventResolutionOutput,
)
from worker_ml.llm.runner import LlmTaskRunner
from worker_ml.llm.schema import prompt_schema_json
from worker_ml.retrieval.vector_index import VectorIndexService


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
        candidate_limit: int,
    ) -> None:
        self._session_factory = session_factory
        self._runner = runner
        self._vector_index = vector_index
        self._model_name = model_name
        self._candidate_limit = candidate_limit

    async def handle(self, job: ClaimedJob) -> EntityResolutionOutput | None:
        if job.article_id is None:
            raise ValueError("entity resolution job requires article_id")
        async with self._session_factory() as session:
            if not await try_mutation_lock(session, ENTITY_MUTATION_ADVISORY_LOCK):
                raise IdentityMutationBusyError("Entity mutation lock is busy")
            card, cases = await _load_card_and_cases(session, job.article_id)
            if card is None:
                return None
            case_ids = {case.id for case in cases}
            provisional = with_provisional_refs(card.card_json.get("entities", []), "entity")
            if not provisional:
                return None
            retrieval_started_at = time.monotonic()
            candidates = await self._load_candidates(session, provisional)
            retrieval_duration_seconds = time.monotonic() - retrieval_started_at
            resolution_json = _resolution_json(provisional, candidates, cases)
            schema_json = prompt_schema_json(EntityResolutionOutput)
            result = await self._runner.run_with_provenance(
                run_type="entity_resolution",
                model_name=self._model_name,
                variables={
                    "resolution_json": resolution_json,
                    "schema_json": schema_json,
                },
                metadata={
                    "article_id": str(job.article_id),
                    "job_id": str(job.id),
                    "retrieval_duration_seconds": round(retrieval_duration_seconds, 6),
                    "retrieved_candidate_count": sum(map(len, candidates)),
                    "retrieved_candidate_counts": list(map(len, candidates)),
                    "provisional_item_count": len(provisional),
                    "prompt_size_chars": prompt_size_chars(resolution_json, schema_json),
                },
            )
            output = cast(EntityResolutionOutput, result.output)
            validate_coverage(provisional, output.entities, case_ids)
            candidate_ids = {
                item["provisional_ref"]: {candidate["entity_id"] for candidate in item_candidates}
                for item, item_candidates in zip(provisional, candidates, strict=True)
            }
            output = normalize_invalid_entity_links(provisional, output, candidate_ids)
            affected = await _persist_entities(
                session,
                article_id=job.article_id,
                provisional=provisional,
                output=output,
                run_id=result.run_id,
                candidate_ids=candidate_ids,
            )
            await rebuild_case_entities(session, affected)
            for entity_id in {entity_id for _, entity_id in affected}:
                entity = await session.get(Entity, entity_id)
                if entity is not None:
                    await self._vector_index.upsert_entity(entity.id, entity_vector_payload(entity))
            await session.commit()
            return output

    async def _load_candidates(
        self, session: AsyncSession, provisional: list[dict[str, Any]]
    ) -> list[list[dict[str, Any]]]:
        result_groups = await self._vector_index.search_entities_batch(
            [entity_query(item) for item in provisional],
            limit=self._candidate_limit,
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
                    **entity_vector_payload(by_id[result.id]).model_dump(mode="json"),
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
        candidate_limit: int,
    ) -> None:
        self._session_factory = session_factory
        self._runner = runner
        self._vector_index = vector_index
        self._model_name = model_name
        self._candidate_limit = candidate_limit

    async def handle(self, job: ClaimedJob) -> EventResolutionOutput | None:
        if job.article_id is None:
            raise ValueError("event resolution job requires article_id")
        async with self._session_factory() as session:
            if not await try_mutation_lock(session, EVENT_MUTATION_ADVISORY_LOCK):
                raise IdentityMutationBusyError("Event mutation lock is busy")
            card, cases = await _load_card_and_cases(session, job.article_id)
            if card is None:
                return None
            case_ids = {case.id for case in cases}
            provisional = with_provisional_refs(card.card_json.get("events", []), "event")
            if not provisional:
                return None
            retrieval_started_at = time.monotonic()
            candidates = await self._load_candidates(session, provisional)
            retrieval_duration_seconds = time.monotonic() - retrieval_started_at
            resolution_json = _resolution_json(provisional, candidates, cases)
            schema_json = prompt_schema_json(EventResolutionOutput)
            result = await self._runner.run_with_provenance(
                run_type="event_resolution",
                model_name=self._model_name,
                variables={
                    "resolution_json": resolution_json,
                    "schema_json": schema_json,
                    "current_date_kyiv": datetime.now(ZoneInfo("Europe/Kyiv")).date().isoformat(),
                },
                metadata={
                    "article_id": str(job.article_id),
                    "job_id": str(job.id),
                    "retrieval_duration_seconds": round(retrieval_duration_seconds, 6),
                    "retrieved_candidate_count": sum(map(len, candidates)),
                    "retrieved_candidate_counts": list(map(len, candidates)),
                    "provisional_item_count": len(provisional),
                    "prompt_size_chars": prompt_size_chars(resolution_json, schema_json),
                },
            )
            output = cast(EventResolutionOutput, result.output)
            validate_coverage(provisional, output.events, case_ids)
            candidate_ids = {
                item["provisional_ref"]: {candidate["event_id"] for candidate in item_candidates}
                for item, item_candidates in zip(provisional, candidates, strict=True)
            }
            output = normalize_invalid_event_links(provisional, output, candidate_ids)
            output = normalize_event_link_anchors(provisional, output, candidates)
            affected = await _persist_events(
                session,
                article_id=job.article_id,
                provisional=provisional,
                output=output,
                run_id=result.run_id,
                candidate_ids=candidate_ids,
            )
            await rebuild_case_events(session, affected)
            for event_id in {event_id for _, event_id in affected}:
                event = await session.get(Event, event_id)
                if event is not None:
                    await self._vector_index.upsert_event(event.id, event_vector_payload(event))
            for case_id in {case_id for case_id, _ in affected}:
                case = await session.get(Case, case_id)
                if case is not None:
                    await self._vector_index.upsert_case(case.id, case_vector_payload(case))
            await session.commit()
            return output

    async def _load_candidates(
        self, session: AsyncSession, provisional: list[dict[str, Any]]
    ) -> list[list[dict[str, Any]]]:
        result_groups = await self._vector_index.search_events_batch(
            [event_query(item) for item in provisional],
            limit=self._candidate_limit,
        )
        candidate_ids = {result.id for group in result_groups for result in group}
        rows = list((await session.scalars(select(Event).where(Event.id.in_(candidate_ids)))).all())
        by_id = {row.id: row for row in rows}
        return [
            [
                {
                    "event_id": str(result.id),
                    "score": result.score,
                    **event_vector_payload(by_id[result.id]).model_dump(mode="json"),
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
        assignments = merged_assignments(decisions)
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
        for case_id, reason in merged_assignments(decisions).items():
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
    year, month, day = date_parts(decision.event_date, decision.event_date_precision)
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
    enrich_event_date(existing_event, year, month, day, decision.event_date_precision)
    if existing_event.location_uk is not None and decision.location_uk is not None:
        if existing_event.location_uk.casefold() != decision.location_uk.casefold():
            raise ValueError("event decision conflicts with existing location")
    elif existing_event.location_uk is None:
        existing_event.location_uk = decision.location_uk
    return existing_event


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
    return json_dumps_compact(payload)
