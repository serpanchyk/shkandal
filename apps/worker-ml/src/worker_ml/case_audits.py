"""Recurring Case coherence audits and atomic Case splits."""

from __future__ import annotations

import json
from datetime import UTC, datetime
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
    CaseCoherenceAudit,
    CaseEntity,
    CaseEvent,
    CaseRelation,
)
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from worker_ml.case_resolution import (
    _case_payload,
    _try_case_lock,
)
from worker_ml.identity_resolution import (
    ENTITY_MUTATION_ADVISORY_LOCK,
    EVENT_MUTATION_ADVISORY_LOCK,
    _rebuild_case_entities,
    _rebuild_case_events,
    _try_lock,
)
from worker_ml.llm.contracts import CaseCoherenceAuditOutput
from worker_ml.llm.runner import LlmTaskRunner
from worker_ml.llm.schema import prompt_schema_json
from worker_ml.vector_index import VectorIndexService


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
        model_name: str,
        card_batch_size: int,
    ) -> None:
        self._session_factory = session_factory
        self._runner = runner
        self._vector_index = vector_index
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
            if not await _try_case_lock(session):
                raise CaseAuditSupersededError("case mutation lock is busy")
            if not await _try_lock(session, ENTITY_MUTATION_ADVISORY_LOCK):
                raise CaseAuditSupersededError("Entity mutation lock is busy")
            if not await _try_lock(session, EVENT_MUTATION_ADVISORY_LOCK):
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
                    _case_payload(affected_case),
                )
            await session.commit()
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
            return await self._invoke(job, {**case_context, "article_cards": cards}, "final")

        batch_results: list[dict[str, Any]] = []
        for index, batch in enumerate(batches):
            output, _ = await self._invoke(
                job,
                {**case_context, "article_cards": batch},
                f"batch_{index + 1}",
            )
            if output.outcome == "inconclusive":
                return output, None
            batch_results.append(output.model_dump(mode="json"))
        return await self._invoke(
            job,
            {**case_context, "batch_audits": batch_results},
            "reconciliation",
        )

    async def _invoke(
        self,
        job: ClaimedJob,
        payload: dict[str, Any],
        phase: str,
    ) -> tuple[CaseCoherenceAuditOutput, UUID | None]:
        result = await self._runner.run_with_provenance(
            run_type="case_coherence_audit",
            model_name=self._model_name,
            variables={
                "case_json": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                "schema_json": prompt_schema_json(CaseCoherenceAuditOutput),
            },
            metadata={"case_id": str(job.case_id), "job_id": str(job.id), "phase": phase},
        )
        return cast(CaseCoherenceAuditOutput, result.output), result.run_id


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
    unknown = assigned - article_ids
    missing = article_ids - assigned
    if unknown:
        raise ValueError(f"audit references unknown article ids: {sorted(unknown)}")
    if missing:
        raise ValueError(f"audit omits article ids: {sorted(missing)}")


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
    await _rebuild_case_entities(session, affected_entity_pairs)
    await _rebuild_case_events(session, affected_event_pairs)
    for target in story_cases.values():
        await _refresh_case_counts(session, target)
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
    case.evidence_revision = evidence_revision + (1 if output.outcome == "split" else 0)
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


async def _refresh_case_counts(session: AsyncSession, case: Case) -> None:
    row = (
        await session.execute(
            select(
                func.count(CaseArticle.id),
                func.min(Article.published_at),
                func.max(Article.published_at),
            )
            .join(Article, Article.id == CaseArticle.article_id)
            .where(CaseArticle.case_id == case.id)
        )
    ).one()
    case.article_count = row[0]
    case.first_seen_at = row[1]
    case.last_updated_at = row[2]
    case.event_count = int(
        await session.scalar(
            select(func.count()).select_from(CaseEvent).where(CaseEvent.case_id == case.id)
        )
        or 0
    )


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
