"""Automatic Case public-interest and duplicate audits."""

from __future__ import annotations

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
)
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from worker_ml.cases.audits import load_case_article_cards
from worker_ml.cases.publication import (
    ENTITY_MUTATION_ADVISORY_LOCK,
    EVENT_MUTATION_ADVISORY_LOCK,
    rebuild_case_entities,
    rebuild_case_events,
    refresh_case_counts,
    try_case_mutation_lock,
    try_mutation_lock,
)
from worker_ml.llm.budgeting import (
    compact_article_cards,
    count_metadata,
    json_dumps_compact,
    lifecycle_sample,
    prompt_size_chars,
)
from worker_ml.llm.contracts import CaseDuplicateAuditOutput, CasePublicInterestAuditOutput
from worker_ml.llm.runner import LlmTaskRunner
from worker_ml.llm.schema import prompt_schema_json
from worker_ml.retrieval.vector_index import VectorIndexService

AUDIT_CASE_DUPLICATES_JOB = "audit_case_duplicates"
REFRESH_CASE_JOB = "refresh_case"
MAX_REVIEW_EVIDENCE_CARDS = 40


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
        card_limit: int = MAX_REVIEW_EVIDENCE_CARDS,
    ) -> None:
        self._session_factory = session_factory
        self._runner = runner
        self._vector_index = vector_index
        self._job_store = job_store
        self._model_name = model_name
        self._card_limit = card_limit

    async def handle(self, job: ClaimedJob) -> CasePublicInterestAuditOutput | None:
        if job.case_id is None:
            raise ValueError("Case public-interest audit requires case_id")
        async with self._session_factory() as session:
            case = await session.get(Case, job.case_id)
            if case is None or case.status != "active":
                return None
            revision = case.evidence_revision
            cards = await load_case_article_cards(session, case.id)
            included_cards = _review_cards(cards, self._card_limit)
            payload = _case_payload(case, included_cards)
        case_json = json_dumps_compact(payload)
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
                **count_metadata(
                    prefix="article_card",
                    original_count=len(cards),
                    included_count=len(included_cards),
                ),
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
        if outcome == "keep" and await self._has_duplicate_candidate(job.case_id):
            await self._job_store.enqueue_case_job(
                job_type=AUDIT_CASE_DUPLICATES_JOB,
                case_id=job.case_id,
                payload={"case_id": str(job.case_id)},
            )
        return output

    async def _has_duplicate_candidate(self, case_id: UUID) -> bool:
        async with self._session_factory() as session:
            case = await session.get(Case, case_id)
            if case is None or case.status != "active":
                return False
            return bool(await _duplicate_candidate_ids(session, case))


class CaseDuplicateAuditJobHandler:
    """Audit active Cases whose shared Articles indicate a possible duplicate."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        runner: LlmTaskRunner,
        vector_index: VectorIndexService,
        job_store: ArticleJobStore,
        *,
        model_name: str,
        card_limit: int = MAX_REVIEW_EVIDENCE_CARDS,
        refresh_case_priority: int = 100,
    ) -> None:
        self._session_factory = session_factory
        self._runner = runner
        self._vector_index = vector_index
        self._job_store = job_store
        self._model_name = model_name
        self._card_limit = card_limit
        self._refresh_case_priority = refresh_case_priority

    async def handle(self, job: ClaimedJob) -> list[CaseDuplicateAuditOutput] | None:
        if job.case_id is None:
            raise ValueError("Case duplicate audit requires case_id")
        async with self._session_factory() as session:
            case = await session.get(Case, job.case_id)
            if case is None or case.status != "active":
                return None
            candidate_ids = await _duplicate_candidate_ids(session, case)
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

    async def _audit_pair(
        self, job: ClaimedJob, case_id: UUID, candidate_id: UUID
    ) -> CaseDuplicateAuditOutput | None:
        async with self._session_factory() as session:
            cases = [await session.get(Case, value) for value in (case_id, candidate_id)]
            if any(case is None or case.status != "active" for case in cases):
                return None
            case_a, case_b = cast(tuple[Case, Case], tuple(cases))
            revisions = (case_a.evidence_revision, case_b.evidence_revision)
            cards_a = await load_case_article_cards(session, case_a.id)
            cards_b = await load_case_article_cards(session, case_b.id)
            included_a = _review_cards(cards_a, self._card_limit)
            included_b = _review_cards(cards_b, self._card_limit)
            payload = {
                "case_a": _case_payload(case_a, included_a),
                "case_b": _case_payload(case_b, included_b),
            }
        cases_json = json_dumps_compact(payload)
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
                "article_card_count": len(cards_a) + len(cards_b),
                "included_article_card_count": len(included_a) + len(included_b),
                "input_truncated": len(included_a) < len(cards_a) or len(included_b) < len(cards_b),
                "prompt_size_chars": prompt_size_chars(cases_json, schema_json),
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
                    job_type=REFRESH_CASE_JOB,
                    case_id=survivor.id,
                    payload={"case_id": str(survivor.id)},
                    priority=self._refresh_case_priority,
                )
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

    return compact_article_cards(cards)


def _review_cards(cards: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Return compact lifecycle evidence for public-interest and duplicate audits."""

    return lifecycle_sample(_compact_cards(cards), limit=limit)


async def _duplicate_candidate_ids(session: AsyncSession, current: Case) -> list[UUID]:
    """Return active Cases sharing at least 30% of the smaller Case's Articles."""

    shared = (
        select(
            CaseArticle.case_id.label("other_id"),
            func.count(CaseArticle.article_id.distinct()).label("shared_count"),
        )
        .where(
            CaseArticle.case_id != current.id,
            CaseArticle.article_id.in_(
                select(CaseArticle.article_id).where(CaseArticle.case_id == current.id)
            ),
        )
        .group_by(CaseArticle.case_id)
        .subquery()
    )
    smaller_count = func.least(current.article_count, Case.article_count)
    return list(
        (
            await session.scalars(
                select(shared.c.other_id)
                .join(Case, Case.id == shared.c.other_id)
                .where(
                    Case.status == "active",
                    shared.c.shared_count >= 1,
                    shared.c.shared_count * 10 >= smaller_count * 3,
                )
                .order_by(shared.c.shared_count.desc(), Case.created_at.asc(), Case.id.asc())
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


def _case_vector(case: Case) -> Any:
    from worker_ml.cases.publication import case_vector_payload

    return case_vector_payload(case)
