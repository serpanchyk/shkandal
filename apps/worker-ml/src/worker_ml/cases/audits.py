"""Recurring Case coherence audits and atomic Case splits."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

from shkandal_database.jobs import ArticleJobStore, ClaimedJob
from shkandal_database.models import (
    Article,
    ArticleCard,
    ArticleEntity,
    ArticleEntityCase,
    ArticleEvent,
    ArticleEventCase,
    Case,
    CaseArticle,
    CaseCoherenceAudit,
    CaseEntity,
    CaseEvent,
    CaseRelation,
)
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from worker_ml.cases.publication import (
    ENTITY_MUTATION_ADVISORY_LOCK,
    EVENT_MUTATION_ADVISORY_LOCK,
    case_vector_payload,
    rebuild_case_entities,
    rebuild_case_events,
    refresh_case_counts,
    try_case_mutation_lock,
    try_mutation_lock,
)
from worker_ml.llm.contracts import CaseCoherenceAuditOutput
from worker_ml.llm.runner import LlmTaskRunner
from worker_ml.llm.schema import prompt_schema_json
from worker_ml.retrieval.vector_index import VectorIndexService


class CaseAuditSupersededError(RuntimeError):
    """The Case evidence changed while an audit was being prepared."""


class CaseCoherenceAuditJobHandler:
    """Audit one Case and atomically publish a safe split when required."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        runner: LlmTaskRunner,
        vector_index: VectorIndexService,
        *,
        job_store: ArticleJobStore | None = None,
        model_name: str,
        card_batch_size: int,
    ) -> None:
        self._session_factory = session_factory
        self._runner = runner
        self._vector_index = vector_index
        self._job_store = job_store
        self._model_name = model_name
        self._card_batch_size = max(2, card_batch_size)

    async def handle(self, job: ClaimedJob) -> CaseCoherenceAuditOutput | None:
        """Prepare an audit without locks, then publish it under the Case lock."""

        if job.case_id is None:
            raise ValueError("Case coherence audit job requires case_id")
        async with self._session_factory() as session:
            case = await session.get(Case, job.case_id)
            if case is None or case.status != "active":
                return None
            evidence_revision = case.evidence_revision
            cards = await _audit_cards(session, case.id)
            if not cards:
                return None
            case_context = {
                "case_id": str(case.id),
                "title_uk": case.title_uk,
                "summary_uk": case.summary_uk,
            }

        output, run_id = await self._run_audit(
            job=job,
            case_context=case_context,
            cards=cards,
        )
        _validate_article_coverage(output, {card["article_id"] for card in cards})

        async with self._session_factory() as session:
            if not await try_case_mutation_lock(session):
                raise CaseAuditSupersededError("case mutation lock is busy")
            if not await try_mutation_lock(session, ENTITY_MUTATION_ADVISORY_LOCK):
                raise CaseAuditSupersededError("Entity mutation lock is busy")
            if not await try_mutation_lock(session, EVENT_MUTATION_ADVISORY_LOCK):
                raise CaseAuditSupersededError("Event mutation lock is busy")
            case = await session.get(Case, job.case_id)
            if case is None or case.status != "active":
                return None
            if case.evidence_revision != evidence_revision:
                session.add(
                    CaseCoherenceAudit(
                        case_id=case.id,
                        evidence_revision=evidence_revision,
                        outcome="superseded",
                        llm_run_id=run_id,
                        result_json=output.model_dump(mode="json"),
                    )
                )
                await session.commit()
                raise CaseAuditSupersededError("Case evidence changed during audit")
            if output.outcome == "inconclusive":
                await _record_audit(session, case, evidence_revision, output, run_id)
                await session.commit()
                return output
            affected = await _apply_decisive_audit(
                session,
                case=case,
                evidence_revision=evidence_revision,
                output=output,
                run_id=run_id,
            )
            for affected_case in affected:
                await self._vector_index.upsert_case(
                    affected_case.id,
                    case_vector_payload(affected_case),
                )
            await session.commit()
        if self._job_store is not None:
            for affected_case in affected:
                await self._job_store.enqueue_case_job(
                    job_type="audit_case_public_interest",
                    case_id=affected_case.id,
                    payload={"case_id": str(affected_case.id)},
                )
        return output

    async def _run_audit(
        self,
        *,
        job: ClaimedJob,
        case_context: dict[str, Any],
        cards: list[dict[str, Any]],
    ) -> tuple[CaseCoherenceAuditOutput, UUID | None]:
        batches = [
            cards[index : index + self._card_batch_size]
            for index in range(0, len(cards), self._card_batch_size)
        ]
        if len(batches) == 1:
            return await self._invoke_with_coverage_retry(
                job=job,
                payload={**case_context, "article_cards": cards},
                relevant_cards=cards,
                phase="final",
            )

        batch_results: list[dict[str, Any]] = []
        evidence_groups: list[dict[str, Any]] = []
        group_articles: dict[str, list[str]] = {}
        for index, batch in enumerate(batches):
            output, _ = await self._invoke_with_coverage_retry(
                job=job,
                payload={**case_context, "article_cards": batch},
                relevant_cards=batch,
                phase=f"batch_{index + 1}",
            )
            if output.outcome == "inconclusive":
                return output, None
            batch_results.append(output.model_dump(mode="json"))
            assigned = {article_id for story in output.stories for article_id in story.article_ids}
            for story_index, story in enumerate(output.stories):
                group_ref = f"group_{index + 1}_{story_index + 1}"
                group_articles[group_ref] = story.article_ids
                evidence_groups.append(
                    {
                        "article_id": group_ref,
                        "title_uk": story.title_uk,
                        "summary_uk": story.summary_uk,
                        "reason_uk": story.reason_uk,
                    }
                )
            for detached_index, detached in enumerate(output.detached_articles):
                if detached.article_id in assigned:
                    continue
                group_ref = f"group_{index + 1}_detached_{detached_index + 1}"
                group_articles[group_ref] = [detached.article_id]
                evidence_groups.append(
                    {
                        "article_id": group_ref,
                        "title_uk": "Від'єднана стаття",
                        "summary_uk": detached.reason_uk,
                        "reason_uk": detached.reason_uk,
                    }
                )
        output, run_id = await self._invoke_with_coverage_retry(
            job=job,
            payload={
                **case_context,
                "batch_audits": batch_results,
                "evidence_groups": evidence_groups,
            },
            relevant_cards=evidence_groups,
            phase="reconciliation",
        )
        return _expand_evidence_groups(output, group_articles), run_id

    async def _invoke_with_coverage_retry(
        self,
        *,
        job: ClaimedJob,
        payload: dict[str, Any],
        relevant_cards: list[dict[str, Any]],
        phase: str,
    ) -> tuple[CaseCoherenceAuditOutput, UUID | None]:
        output, run_id = await self._invoke(job, payload, phase)
        article_ids = {card["article_id"] for card in relevant_cards}
        try:
            _validate_article_coverage(output, article_ids)
        except ValueError as exc:
            output, run_id = await self._invoke(
                job,
                {
                    **payload,
                    "article_cards": relevant_cards,
                    "previous_invalid_audit": output.model_dump(mode="json"),
                    "coverage_validation_error": str(exc),
                },
                f"{phase}_coverage_retry",
            )
            try:
                _validate_article_coverage(output, article_ids)
            except ValueError:
                return _inconclusive_coverage_fallback(), run_id
        return output, run_id

    async def _invoke(
        self,
        job: ClaimedJob,
        payload: dict[str, Any],
        phase: str,
    ) -> tuple[CaseCoherenceAuditOutput, UUID | None]:
        case_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        schema_json = prompt_schema_json(CaseCoherenceAuditOutput)
        result = await self._runner.run_with_provenance(
            run_type="case_coherence_audit",
            model_name=self._model_name,
            variables={
                "case_json": case_json,
                "schema_json": schema_json,
            },
            metadata={
                "case_id": str(job.case_id),
                "job_id": str(job.id),
                "phase": phase,
                "card_count": _audit_card_count(payload),
                "prompt_size_chars": len(case_json) + len(schema_json),
            },
        )
        return cast(CaseCoherenceAuditOutput, result.output), result.run_id


def _audit_card_count(payload: dict[str, Any]) -> int:
    cards = payload.get("article_cards", payload.get("evidence_groups", []))
    return len(cards) if isinstance(cards, list) else 0


async def _audit_cards(session: AsyncSession, case_id: UUID) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(Article.id, Article.published_at, ArticleCard)
            .join(ArticleCard, ArticleCard.article_id == Article.id)
            .join(CaseArticle, CaseArticle.article_id == Article.id)
            .where(CaseArticle.case_id == case_id)
            .order_by(Article.published_at.asc().nulls_last(), Article.created_at.asc())
        )
    ).all()
    return [
        {
            "article_id": str(article_id),
            "published_at": published_at.isoformat() if published_at else None,
            "title_uk": card.title_uk,
            "summary_uk": card.summary_uk,
            **card.card_json,
        }
        for article_id, published_at, card in rows
    ]


def _validate_article_coverage(output: CaseCoherenceAuditOutput, article_ids: set[str]) -> None:
    if output.outcome == "inconclusive":
        return
    assigned = {article_id for story in output.stories for article_id in story.article_ids}
    detached = {item.article_id for item in output.detached_articles}
    unknown = (assigned | detached) - article_ids
    missing = article_ids - assigned - detached
    if assigned & detached:
        duplicates = sorted(assigned & detached)
        raise ValueError(f"audit both assigns and detaches article ids: {duplicates}")
    if unknown:
        raise ValueError(f"audit references unknown article ids: {sorted(unknown)}")
    if missing:
        raise ValueError(f"audit omits article ids: {sorted(missing)}")


def _inconclusive_coverage_fallback() -> CaseCoherenceAuditOutput:
    return CaseCoherenceAuditOutput(
        diagnosis={
            "shared_specific_core_uk": None,
            "shared_only_broad_theme_uk": None,
            "merge_blockers_uk": [],
            "split_story_cores_uk": [],
            "detached_article_signals_uk": [],
            "coherence_test_uk": "Недостатньо доказів для одного конкретного формулювання.",
        },
        outcome="inconclusive",
        reason_uk=(
            "Неможливо безпечно підтвердити повне покриття статей після повторної перевірки."
        ),
        stories=[],
    )


def _expand_evidence_groups(
    output: CaseCoherenceAuditOutput,
    group_articles: dict[str, list[str]],
) -> CaseCoherenceAuditOutput:
    """Expand reconciliation group refs into deterministic original Article IDs."""

    if output.outcome == "inconclusive":
        return output
    payload = output.model_dump(mode="json")
    for story in payload["stories"]:
        story["article_ids"] = list(
            dict.fromkeys(
                article_id
                for group_ref in story["article_ids"]
                for article_id in group_articles[group_ref]
            )
        )
    payload["detached_articles"] = [
        {"article_id": article_id, "reason_uk": detached["reason_uk"]}
        for detached in payload["detached_articles"]
        for article_id in group_articles[detached["article_id"]]
    ]
    return CaseCoherenceAuditOutput.model_validate(payload)


async def _apply_decisive_audit(
    session: AsyncSession,
    *,
    case: Case,
    evidence_revision: int,
    output: CaseCoherenceAuditOutput,
    run_id: UUID | None,
) -> list[Case]:
    now = datetime.now(UTC)
    story_cases: dict[str, Case] = {"original": case}
    original_story = next(story for story in output.stories if story.story_ref == "original")
    case.title_uk = original_story.title_uk
    case.summary_uk = original_story.summary_uk
    for story in output.stories:
        if story.story_ref == "original":
            continue
        new_id = uuid4()
        new_case = Case(
            id=new_id,
            slug=f"case-{new_id.hex}",
            title_uk=story.title_uk,
            summary_uk=story.summary_uk,
            status="active",
            evidence_revision=1,
            last_audited_revision=1,
            last_audited_at=now,
        )
        session.add(new_case)
        story_cases[story.story_ref] = new_case
    await session.flush()

    old_article_ids = set(
        (
            await session.scalars(
                select(CaseArticle.article_id).where(CaseArticle.case_id == case.id)
            )
        ).all()
    )
    await session.execute(delete(CaseArticle).where(CaseArticle.case_id == case.id))
    await session.execute(delete(ArticleEntityCase).where(ArticleEntityCase.case_id == case.id))
    await session.execute(delete(ArticleEventCase).where(ArticleEventCase.case_id == case.id))
    await session.execute(delete(CaseEntity).where(CaseEntity.case_id == case.id))
    await session.execute(delete(CaseEvent).where(CaseEvent.case_id == case.id))

    affected_entity_pairs: set[tuple[UUID, UUID]] = set()
    affected_event_pairs: set[tuple[UUID, UUID]] = set()
    for story in output.stories:
        target = story_cases[story.story_ref]
        for article_id_text in story.article_ids:
            article_id = UUID(article_id_text)
            if article_id not in old_article_ids:
                raise ValueError("audit article disappeared before split application")
            await session.execute(
                insert(CaseArticle)
                .values(
                    case_id=target.id,
                    article_id=article_id,
                    llm_run_id=run_id,
                    link_reason_uk=story.reason_uk,
                    confidence=Decimal("1"),
                )
                .on_conflict_do_nothing(
                    index_elements=[CaseArticle.case_id, CaseArticle.article_id]
                )
            )
            affected_entity_pairs |= await _assign_article_entities(
                session, article_id, target.id, run_id, story.reason_uk
            )
            affected_event_pairs |= await _assign_article_events(
                session, article_id, target.id, run_id, story.reason_uk
            )
    await rebuild_case_entities(session, affected_entity_pairs)
    await rebuild_case_events(session, affected_event_pairs)
    for target in story_cases.values():
        await refresh_case_counts(session, target)
    for target in story_cases.values():
        if target.id == case.id:
            continue
        case_a, case_b = sorted((case.id, target.id))
        await session.execute(
            insert(CaseRelation)
            .values(case_a_id=case_a, case_b_id=case_b, relation_type="related", llm_run_id=run_id)
            .on_conflict_do_nothing(
                index_elements=[
                    CaseRelation.case_a_id,
                    CaseRelation.case_b_id,
                    CaseRelation.relation_type,
                ]
            )
        )
    evidence_changed = output.outcome == "split" or bool(output.detached_articles)
    case.evidence_revision = evidence_revision + int(evidence_changed)
    case.last_audited_revision = case.evidence_revision
    case.last_audited_at = now
    session.add(
        CaseCoherenceAudit(
            case_id=case.id,
            evidence_revision=evidence_revision,
            outcome=output.outcome,
            llm_run_id=run_id,
            result_json=output.model_dump(mode="json"),
        )
    )
    await session.flush()
    return list(story_cases.values())


async def _assign_article_entities(
    session: AsyncSession,
    article_id: UUID,
    case_id: UUID,
    run_id: UUID | None,
    reason: str,
) -> set[tuple[UUID, UUID]]:
    rows = (
        await session.execute(
            select(ArticleEntity.id, ArticleEntity.entity_id).where(
                ArticleEntity.article_id == article_id
            )
        )
    ).all()
    for article_entity_id, _ in rows:
        await session.execute(
            insert(ArticleEntityCase)
            .values(
                article_entity_id=article_entity_id,
                case_id=case_id,
                llm_run_id=run_id,
                relevance_reason_uk=reason,
            )
            .on_conflict_do_nothing(
                index_elements=[ArticleEntityCase.article_entity_id, ArticleEntityCase.case_id]
            )
        )
    return {(case_id, entity_id) for _, entity_id in rows}


async def _assign_article_events(
    session: AsyncSession,
    article_id: UUID,
    case_id: UUID,
    run_id: UUID | None,
    reason: str,
) -> set[tuple[UUID, UUID]]:
    rows = (
        await session.execute(
            select(ArticleEvent.id, ArticleEvent.event_id).where(
                ArticleEvent.article_id == article_id
            )
        )
    ).all()
    for article_event_id, _ in rows:
        await session.execute(
            insert(ArticleEventCase)
            .values(
                article_event_id=article_event_id,
                case_id=case_id,
                llm_run_id=run_id,
                relevance_reason_uk=reason,
            )
            .on_conflict_do_nothing(
                index_elements=[ArticleEventCase.article_event_id, ArticleEventCase.case_id]
            )
        )
    return {(case_id, event_id) for _, event_id in rows}


async def _record_audit(
    session: AsyncSession,
    case: Case,
    evidence_revision: int,
    output: CaseCoherenceAuditOutput,
    run_id: UUID | None,
) -> None:
    case.last_audited_revision = evidence_revision
    case.last_audited_at = datetime.now(UTC)
    session.add(
        CaseCoherenceAudit(
            case_id=case.id,
            evidence_revision=evidence_revision,
            outcome=output.outcome,
            llm_run_id=run_id,
            result_json=output.model_dump(mode="json"),
        )
    )
