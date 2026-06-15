"""Automatic Case public-interest and duplicate audits."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from shkandal_database.jobs import ArticleJobStore, ClaimedJob
from shkandal_database.models import (
    ArticleEntity,
    ArticleEntityCase,
    ArticleEvent,
    ArticleEventCase,
    Case,
    CaseArticle,
    CaseDuplicateAudit,
    CasePublicInterestAudit,
    CaseRelation,
)
from sqlalchemy import case as sql_case
from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from worker_ml.cases.audits import _audit_cards
from worker_ml.cases.publication import (
    ENTITY_MUTATION_ADVISORY_LOCK,
    EVENT_MUTATION_ADVISORY_LOCK,
    rebuild_case_entities,
    rebuild_case_events,
    refresh_case_counts,
    try_case_mutation_lock,
    try_mutation_lock,
)
from worker_ml.llm.contracts import CaseDuplicateAuditOutput, CasePublicInterestAuditOutput
from worker_ml.llm.runner import LlmTaskRunner
from worker_ml.llm.schema import prompt_schema_json
from worker_ml.retrieval.vector_index import VectorIndexService

AUDIT_CASE_DUPLICATES_JOB = "audit_case_duplicates"
UPDATE_CASE_COPY_JOB = "update_case_copy"


class CasePublicInterestAuditJobHandler:
    """Hide Cases that are not durable public-interest stories."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        runner: LlmTaskRunner,
        vector_index: VectorIndexService,
        job_store: ArticleJobStore,
        *,
        model_name: str,
    ) -> None:
        self._session_factory = session_factory
        self._runner = runner
        self._vector_index = vector_index
        self._job_store = job_store
        self._model_name = model_name

    async def handle(self, job: ClaimedJob) -> CasePublicInterestAuditOutput | None:
        if job.case_id is None:
            raise ValueError("Case public-interest audit requires case_id")
        async with self._session_factory() as session:
            case = await session.get(Case, job.case_id)
            if case is None or case.status != "active":
                return None
            revision = case.evidence_revision
            payload = _case_payload(case, _compact_cards(await _audit_cards(session, case.id)))
        case_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        schema_json = prompt_schema_json(CasePublicInterestAuditOutput)
        result = await self._runner.run_with_provenance(
            run_type="case_public_interest_audit",
            model_name=self._model_name,
            variables={
                "case_json": case_json,
                "schema_json": schema_json,
            },
            metadata={
                "case_id": str(job.case_id),
                "job_id": str(job.id),
                "phase": "final",
                "card_count": len(payload["article_cards"]),
                "prompt_size_chars": len(case_json) + len(schema_json),
            },
        )
        output = cast(CasePublicInterestAuditOutput, result.output)
        async with self._session_factory() as session:
            if not await try_case_mutation_lock(session):
                raise RuntimeError("case mutation lock is busy")
            case = await session.get(Case, job.case_id)
            if case is None or case.status != "active":
                return None
            outcome: str = output.outcome
            if case.evidence_revision != revision:
                outcome = "superseded"
            elif outcome == "hide":
                case.status = "hidden"
                await self._vector_index.delete_case(case.id)
            case.last_interest_audited_revision = revision
            case.last_interest_audited_at = datetime.now(UTC)
            session.add(
                CasePublicInterestAudit(
                    case_id=case.id,
                    evidence_revision=revision,
                    outcome=outcome,
                    llm_run_id=result.run_id,
                    result_json=output.model_dump(mode="json"),
                )
            )
            await session.commit()
        if outcome == "keep":
            await self._job_store.enqueue_case_job(
                job_type=AUDIT_CASE_DUPLICATES_JOB,
                case_id=job.case_id,
                payload={"case_id": str(job.case_id)},
            )
        return output


class CaseDuplicateAuditJobHandler:
    """Resolve possible duplicate relations for one active Case."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        runner: LlmTaskRunner,
        vector_index: VectorIndexService,
        job_store: ArticleJobStore,
        *,
        model_name: str,
    ) -> None:
        self._session_factory = session_factory
        self._runner = runner
        self._vector_index = vector_index
        self._job_store = job_store
        self._model_name = model_name

    async def handle(self, job: ClaimedJob) -> list[CaseDuplicateAuditOutput] | None:
        if job.case_id is None:
            raise ValueError("Case duplicate audit requires case_id")
        await self._ensure_overlap_candidates(job.case_id)
        async with self._session_factory() as session:
            case = await session.get(Case, job.case_id)
            if case is None or case.status != "active":
                return None
            candidate_ids = await _possible_duplicate_ids(session, case.id)
        outputs: list[CaseDuplicateAuditOutput] = []
        for candidate_id in candidate_ids:
            output = await self._audit_pair(job, case.id, candidate_id)
            if output is not None:
                outputs.append(output)
        async with self._session_factory() as session:
            case = await session.get(Case, job.case_id)
            if case is not None and case.status == "active":
                case.last_duplicate_audited_revision = case.evidence_revision
                case.last_duplicate_audited_at = datetime.now(UTC)
                await session.commit()
        return outputs

    async def _ensure_overlap_candidates(self, case_id: UUID) -> None:
        async with self._session_factory() as session:
            case = await session.get(Case, case_id)
            if case is None or case.status != "active":
                return
            shared = (
                select(
                    CaseArticle.case_id.label("other_id"),
                    func.count(CaseArticle.article_id.distinct()).label("shared_count"),
                )
                .where(
                    CaseArticle.case_id != case_id,
                    CaseArticle.article_id.in_(
                        select(CaseArticle.article_id).where(CaseArticle.case_id == case_id)
                    ),
                )
                .group_by(CaseArticle.case_id)
                .subquery()
            )
            rows = (
                await session.execute(
                    select(shared.c.other_id, shared.c.shared_count, Case.article_count)
                    .join(Case, Case.id == shared.c.other_id)
                    .where(Case.status == "active", shared.c.shared_count >= 2)
                )
            ).all()
            for other_id, shared_count, other_count in rows:
                if shared_count * 2 < min(case.article_count, other_count):
                    continue
                case_a, case_b = sorted((case_id, other_id))
                await session.execute(
                    insert(CaseRelation)
                    .values(case_a_id=case_a, case_b_id=case_b, relation_type="possible_duplicate")
                    .on_conflict_do_nothing(
                        index_elements=[
                            CaseRelation.case_a_id,
                            CaseRelation.case_b_id,
                            CaseRelation.relation_type,
                        ]
                    )
                )
            await session.commit()

    async def _audit_pair(
        self, job: ClaimedJob, case_id: UUID, candidate_id: UUID
    ) -> CaseDuplicateAuditOutput | None:
        async with self._session_factory() as session:
            cases = [await session.get(Case, value) for value in (case_id, candidate_id)]
            if any(case is None or case.status != "active" for case in cases):
                return None
            case_a, case_b = cast(tuple[Case, Case], tuple(cases))
            revisions = (case_a.evidence_revision, case_b.evidence_revision)
            payload = {
                "case_a": _case_payload(
                    case_a, _compact_cards(await _audit_cards(session, case_a.id))
                ),
                "case_b": _case_payload(
                    case_b, _compact_cards(await _audit_cards(session, case_b.id))
                ),
            }
        cases_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        schema_json = prompt_schema_json(CaseDuplicateAuditOutput)
        result = await self._runner.run_with_provenance(
            run_type="case_duplicate_audit",
            model_name=self._model_name,
            variables={
                "cases_json": cases_json,
                "schema_json": schema_json,
            },
            metadata={
                "case_id": str(case_id),
                "candidate_case_id": str(candidate_id),
                "job_id": str(job.id),
                "phase": "pair",
                "card_count": sum(
                    len(case_payload["article_cards"]) for case_payload in payload.values()
                ),
                "prompt_size_chars": len(cases_json) + len(schema_json),
            },
        )
        output = cast(CaseDuplicateAuditOutput, result.output)
        await self._apply_pair(case_id, candidate_id, revisions, output, result.run_id)
        return output

    async def _apply_pair(
        self,
        case_id: UUID,
        candidate_id: UUID,
        revisions: tuple[int, int],
        output: CaseDuplicateAuditOutput,
        run_id: UUID | None,
    ) -> None:
        async with self._session_factory() as session:
            for lock in (None, ENTITY_MUTATION_ADVISORY_LOCK, EVENT_MUTATION_ADVISORY_LOCK):
                acquired = (
                    await try_case_mutation_lock(session)
                    if lock is None
                    else await try_mutation_lock(session, lock)
                )
                if not acquired:
                    raise RuntimeError("Case duplicate mutation lock is busy")
            cases = [await session.get(Case, value) for value in (case_id, candidate_id)]
            if any(case is None or case.status != "active" for case in cases):
                return
            case_a, case_b = cast(tuple[Case, Case], tuple(cases))
            outcome: str = output.outcome
            if (case_a.evidence_revision, case_b.evidence_revision) != revisions:
                outcome = "superseded"
            elif outcome == "merge":
                survivor, absorbed = _merge_order(case_a, case_b)
                await _merge_cases(session, survivor, absorbed, run_id)
                await self._vector_index.upsert_case(survivor.id, _case_vector(survivor))
                await self._vector_index.delete_case(absorbed.id)
                await self._job_store.enqueue_case_job(
                    job_type=UPDATE_CASE_COPY_JOB,
                    case_id=survivor.id,
                    payload={"case_id": str(survivor.id)},
                )
            elif outcome in {"related", "distinct"}:
                await _resolve_relation(session, case_a.id, case_b.id, output.outcome, run_id)
            pair_a, pair_b = sorted((case_a.id, case_b.id))
            revisions_by_id = {case_a.id: revisions[0], case_b.id: revisions[1]}
            session.add(
                CaseDuplicateAudit(
                    case_a_id=pair_a,
                    case_b_id=pair_b,
                    case_a_revision=revisions_by_id[pair_a],
                    case_b_revision=revisions_by_id[pair_b],
                    outcome=outcome,
                    llm_run_id=run_id,
                    result_json=output.model_dump(mode="json"),
                )
            )
            await session.commit()


def _case_payload(case: Case, cards: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "case_id": str(case.id),
        "title_uk": case.title_uk,
        "summary_uk": case.summary_uk,
        "article_cards": cards,
    }


def _compact_cards(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep audit evidence bounded while preserving the factual article summaries."""

    return [
        {
            "article_id": card["article_id"],
            "published_at": card.get("published_at"),
            "title_uk": card.get("title_uk"),
            "summary_uk": card.get("summary_uk"),
        }
        for card in cards
    ]


async def _possible_duplicate_ids(session: AsyncSession, case_id: UUID) -> list[UUID]:
    return list(
        (
            await session.scalars(
                select(
                    sql_case(
                        (CaseRelation.case_a_id == case_id, CaseRelation.case_b_id),
                        else_=CaseRelation.case_a_id,
                    )
                ).where(
                    CaseRelation.relation_type == "possible_duplicate",
                    or_(CaseRelation.case_a_id == case_id, CaseRelation.case_b_id == case_id),
                )
            )
        ).all()
    )


def _merge_order(case_a: Case, case_b: Case) -> tuple[Case, Case]:
    ordered = sorted(
        (case_a, case_b), key=lambda case: (-case.article_count, case.created_at, str(case.id))
    )
    return ordered[0], ordered[1]


async def _merge_cases(
    session: AsyncSession, survivor: Case, absorbed: Case, run_id: UUID | None
) -> None:
    article_ids = list(
        (
            await session.scalars(
                select(CaseArticle.article_id).where(CaseArticle.case_id == absorbed.id)
            )
        ).all()
    )
    entity_pairs: set[tuple[UUID, UUID]] = set()
    event_pairs: set[tuple[UUID, UUID]] = set()
    for article_id in article_ids:
        await session.execute(
            insert(CaseArticle)
            .values(
                case_id=survivor.id,
                article_id=article_id,
                llm_run_id=run_id,
                link_reason_uk="Справи автоматично об'єднано як дублікати.",
                confidence=Decimal("1"),
            )
            .on_conflict_do_nothing(index_elements=[CaseArticle.case_id, CaseArticle.article_id])
        )
        for article_entity_id, entity_id in (
            await session.execute(
                select(ArticleEntity.id, ArticleEntity.entity_id).where(
                    ArticleEntity.article_id == article_id
                )
            )
        ).all():
            await session.execute(
                insert(ArticleEntityCase)
                .values(
                    article_entity_id=article_entity_id,
                    case_id=survivor.id,
                    llm_run_id=run_id,
                    relevance_reason_uk="Справи об'єднано.",
                )
                .on_conflict_do_nothing(
                    index_elements=[ArticleEntityCase.article_entity_id, ArticleEntityCase.case_id]
                )
            )
            entity_pairs.add((survivor.id, entity_id))
        for article_event_id, event_id in (
            await session.execute(
                select(ArticleEvent.id, ArticleEvent.event_id).where(
                    ArticleEvent.article_id == article_id
                )
            )
        ).all():
            await session.execute(
                insert(ArticleEventCase)
                .values(
                    article_event_id=article_event_id,
                    case_id=survivor.id,
                    llm_run_id=run_id,
                    relevance_reason_uk="Справи об'єднано.",
                )
                .on_conflict_do_nothing(
                    index_elements=[ArticleEventCase.article_event_id, ArticleEventCase.case_id]
                )
            )
            event_pairs.add((survivor.id, event_id))
    await rebuild_case_entities(session, entity_pairs)
    await rebuild_case_events(session, event_pairs)
    await refresh_case_counts(session, survivor)
    survivor.evidence_revision += 1
    absorbed.status = "merged"
    absorbed.merged_into_case_id = survivor.id
    relation_rows = (
        await session.execute(
            select(CaseRelation).where(
                or_(
                    CaseRelation.case_a_id == absorbed.id,
                    CaseRelation.case_b_id == absorbed.id,
                )
            )
        )
    ).scalars()
    for relation in relation_rows:
        other_id = relation.case_b_id if relation.case_a_id == absorbed.id else relation.case_a_id
        if other_id == survivor.id:
            continue
        pair_a, pair_b = sorted((survivor.id, other_id))
        await session.execute(
            insert(CaseRelation)
            .values(
                case_a_id=pair_a,
                case_b_id=pair_b,
                relation_type=relation.relation_type,
                llm_run_id=run_id,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    CaseRelation.case_a_id,
                    CaseRelation.case_b_id,
                    CaseRelation.relation_type,
                ]
            )
        )
    await session.execute(
        delete(CaseRelation).where(
            or_(CaseRelation.case_a_id == absorbed.id, CaseRelation.case_b_id == absorbed.id)
        )
    )


async def _resolve_relation(
    session: AsyncSession, case_a: UUID, case_b: UUID, outcome: str, run_id: UUID | None
) -> None:
    pair_a, pair_b = sorted((case_a, case_b))
    await session.execute(
        delete(CaseRelation).where(
            CaseRelation.case_a_id == pair_a,
            CaseRelation.case_b_id == pair_b,
            CaseRelation.relation_type == "possible_duplicate",
        )
    )
    if outcome == "related":
        await session.execute(
            insert(CaseRelation)
            .values(case_a_id=pair_a, case_b_id=pair_b, relation_type="related", llm_run_id=run_id)
            .on_conflict_do_nothing(
                index_elements=[
                    CaseRelation.case_a_id,
                    CaseRelation.case_b_id,
                    CaseRelation.relation_type,
                ]
            )
        )


def _case_vector(case: Case) -> Any:
    from worker_ml.cases.publication import case_vector_payload

    return case_vector_payload(case)
