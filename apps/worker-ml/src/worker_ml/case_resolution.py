"""Article-case identity resolution and case-copy regeneration."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

from shkandal_database.jobs import ArticleJobStore, ClaimedJob
from shkandal_database.models import Article, ArticleCard, Case, CaseArticle, CaseRelation, Source
from shkandal_vector_store.schemas import CaseVectorPayload
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from worker_ml.article_cards import get_case_candidate_card
from worker_ml.jobs import (
    RESOLVE_ARTICLE_ENTITIES_JOB,
    RESOLVE_ARTICLE_EVENTS_JOB,
    UPDATE_CASE_COPY_JOB,
)
from worker_ml.llm.contracts import CaseCopyUpdateOutput, CaseResolutionOutput
from worker_ml.llm.runner import LlmTaskRunner
from worker_ml.vector_index import VectorIndexService

CASE_MUTATION_ADVISORY_LOCK = 7_214_801_901
MAX_CASE_CANDIDATES = 12
MAX_CASE_EVIDENCE_CARDS = 40


class CaseMutationBusyError(RuntimeError):
    """Another worker currently owns serialized Case mutation."""


class ArticleCaseResolutionJobHandler:
    """Resolve one case-candidate article into durable Cases."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        job_store: ArticleJobStore,
        runner: LlmTaskRunner,
        vector_index: VectorIndexService,
        *,
        model_name: str,
    ) -> None:
        self._session_factory = session_factory
        self._job_store = job_store
        self._runner = runner
        self._vector_index = vector_index
        self._model_name = model_name

    async def handle(self, job: ClaimedJob) -> CaseResolutionOutput | None:
        """Resolve and persist article-case identity under the global Case lock."""

        if job.article_id is None:
            raise ValueError("article-case resolution job requires article_id")
        async with self._session_factory() as session:
            if not await _try_case_lock(session):
                raise CaseMutationBusyError("case mutation lock is busy")
            card = await get_case_candidate_card(session, article_id=job.article_id)
            if card is None:
                return None
            existing_link = await session.scalar(
                select(CaseArticle.id).where(CaseArticle.article_id == job.article_id).limit(1)
            )
            if existing_link is not None:
                return None
            article_row = (
                await session.execute(
                    select(Article, Source)
                    .join(Source, Source.id == Article.source_id)
                    .where(Article.id == job.article_id)
                )
            ).one()
            article, source = article_row
            candidates = await self._load_candidates(session, card)
            result = await self._runner.run_with_provenance(
                run_type="case_resolution",
                model_name=self._model_name,
                variables={
                    "resolution_json": _resolution_json(article, source, card, candidates),
                    "schema_json": json.dumps(
                        CaseResolutionOutput.model_json_schema(), ensure_ascii=False
                    ),
                },
                metadata={"article_id": str(job.article_id), "job_id": str(job.id)},
            )
            output = cast(CaseResolutionOutput, result.output)
            affected_case_ids = await self._persist_resolution(
                session,
                article=article,
                output=output,
                run_id=result.run_id,
                candidate_ids={candidate["case_id"] for candidate in candidates},
            )
            for case_id in affected_case_ids:
                case = await session.get(Case, case_id)
                if case is not None:
                    await self._vector_index.upsert_case(case.id, _case_payload(case))
            await session.commit()

        for case_id in affected_case_ids:
            await self._job_store.enqueue_case_job(
                job_type=UPDATE_CASE_COPY_JOB,
                case_id=case_id,
                payload={"case_id": str(case_id)},
                max_attempts=job.max_attempts,
            )
        for job_type in (RESOLVE_ARTICLE_ENTITIES_JOB, RESOLVE_ARTICLE_EVENTS_JOB):
            await self._job_store.enqueue_article_job(
                job_type=job_type,
                article_id=job.article_id,
                payload={"article_id": str(job.article_id)},
                max_attempts=job.max_attempts,
            )
        return output

    async def _load_candidates(
        self, session: AsyncSession, card: ArticleCard
    ) -> list[dict[str, Any]]:
        results = await self._vector_index.search_cases(
            _article_card_query(card), limit=MAX_CASE_CANDIDATES
        )
        candidate_ids = [result.id for result in results]
        if not candidate_ids:
            return []
        cases = list(
            (
                await session.scalars(
                    select(Case).where(Case.id.in_(candidate_ids), Case.status == "active")
                )
            ).all()
        )
        by_id = {case.id: case for case in cases}
        return [
            {
                "case_id": str(result.id),
                "score": result.score,
                "title_uk": by_id[result.id].title_uk,
                "summary_uk": by_id[result.id].summary_uk,
                "evidence_titles": await _representative_article_titles(session, result.id),
            }
            for result in results
            if result.id in by_id
        ]

    async def _persist_resolution(
        self,
        session: AsyncSession,
        *,
        article: Article,
        output: CaseResolutionOutput,
        run_id: UUID | None,
        candidate_ids: set[str],
    ) -> set[UUID]:
        resolved: dict[str, UUID] = {}
        affected: set[UUID] = set()
        now = article.published_at or datetime.now(UTC)
        for link in output.existing_case_links:
            if link.case_id not in candidate_ids:
                raise ValueError(f"existing link references non-candidate case: {link.case_id}")
            case_id = UUID(link.case_id)
            resolved[link.case_id] = case_id
            affected.add(case_id)
            await session.execute(
                insert(CaseArticle)
                .values(
                    case_id=case_id,
                    article_id=article.id,
                    llm_run_id=run_id,
                    link_reason_uk=link.link_reason_uk,
                    confidence=Decimal(str(link.confidence)),
                )
                .on_conflict_do_nothing(
                    index_elements=[CaseArticle.case_id, CaseArticle.article_id]
                )
            )
            await session.execute(
                update(Case)
                .where(Case.id == case_id)
                .values(
                    article_count=Case.article_count + 1,
                    last_updated_at=now,
                )
            )
        for decision in output.new_cases:
            case_id = uuid4()
            resolved[decision.new_case_ref] = case_id
            affected.add(case_id)
            session.add(
                Case(
                    id=case_id,
                    slug=f"case-{case_id.hex}",
                    title_uk=decision.title_uk,
                    summary_uk=decision.summary_uk,
                    status="active",
                    first_seen_at=now,
                    last_updated_at=now,
                    article_count=1,
                )
            )
            session.add(
                CaseArticle(
                    case_id=case_id,
                    article_id=article.id,
                    llm_run_id=run_id,
                    link_reason_uk=decision.link_reason_uk,
                    confidence=Decimal(str(decision.confidence)),
                )
            )
        for relation in output.case_relations:
            case_a = _relation_endpoint(relation.case_a_id, relation.case_a_new_ref, resolved)
            case_b = _relation_endpoint(relation.case_b_id, relation.case_b_new_ref, resolved)
            if relation.case_a_id and relation.case_a_id not in candidate_ids:
                raise ValueError("relation references non-candidate existing case")
            if relation.case_b_id and relation.case_b_id not in candidate_ids:
                raise ValueError("relation references non-candidate existing case")
            case_a, case_b = sorted((case_a, case_b))
            await session.execute(
                insert(CaseRelation)
                .values(
                    case_a_id=case_a,
                    case_b_id=case_b,
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
        return affected


class CaseCopyUpdateJobHandler:
    """Regenerate stable reader-facing Case copy from accumulated evidence."""

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

    async def handle(self, job: ClaimedJob) -> CaseCopyUpdateOutput | None:
        """Update one Case and its vector under the global Case lock."""

        if job.case_id is None:
            raise ValueError("case-copy update job requires case_id")
        async with self._session_factory() as session:
            if not await _try_case_lock(session):
                raise CaseMutationBusyError("case mutation lock is busy")
            case = await session.get(Case, job.case_id)
            if case is None:
                return None
            cards = await _case_article_cards(session, case.id)
            result = await self._runner.run_with_provenance(
                run_type="case_copy_update",
                model_name=self._model_name,
                variables={
                    "case_json": json.dumps(
                        {
                            "current_title_uk": case.title_uk,
                            "current_summary_uk": case.summary_uk,
                            "article_cards": _lifecycle_sample(cards, MAX_CASE_EVIDENCE_CARDS),
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    "schema_json": json.dumps(
                        CaseCopyUpdateOutput.model_json_schema(), ensure_ascii=False
                    ),
                },
                metadata={"case_id": str(case.id), "job_id": str(job.id)},
            )
            output = cast(CaseCopyUpdateOutput, result.output)
            if output.title_action == "replace":
                case.title_uk = cast(str, output.replacement_title_uk)
            case.summary_uk = output.summary_uk
            case.last_updated_at = datetime.now(UTC)
            await self._vector_index.upsert_case(case.id, _case_payload(case))
            await session.commit()
            return output


async def _try_case_lock(session: AsyncSession) -> bool:
    statement = select(func.pg_try_advisory_xact_lock(CASE_MUTATION_ADVISORY_LOCK))
    return bool(await session.scalar(statement))


def _case_payload(case: Case) -> CaseVectorPayload:
    return CaseVectorPayload(
        slug=case.slug,
        title_uk=case.title_uk,
        summary_uk=case.summary_uk,
        status=case.status,
        article_count=case.article_count,
        event_count=case.event_count,
        metadata=case.metadata_,
    )


def _article_card_query(card: ArticleCard) -> str:
    values = [card.title_uk, card.summary_uk, *card.card_json.get("case_signature_terms", [])]
    return "\n".join(str(value) for value in values if value)


def _resolution_json(
    article: Article, source: Source, card: ArticleCard, candidates: list[dict[str, Any]]
) -> str:
    return json.dumps(
        {
            "article": {
                "article_id": str(article.id),
                "source_title": article.title,
                "published_at": article.published_at.isoformat() if article.published_at else None,
                "source_name": source.name,
                "card": {
                    "title_uk": card.title_uk,
                    "summary_uk": card.summary_uk,
                    **card.card_json,
                },
            },
            "candidate_cases": candidates,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _relation_endpoint(
    existing_id: str | None,
    new_ref: str | None,
    resolved: dict[str, UUID],
) -> UUID:
    key = existing_id or cast(str, new_ref)
    if key in resolved:
        return resolved[key]
    return UUID(key)


async def _representative_article_titles(session: AsyncSession, case_id: UUID) -> list[str]:
    return list(
        (
            await session.scalars(
                select(ArticleCard.title_uk)
                .join(Article, Article.id == ArticleCard.article_id)
                .join(CaseArticle, CaseArticle.article_id == Article.id)
                .where(CaseArticle.case_id == case_id)
                .order_by(Article.published_at.asc().nulls_last())
                .limit(8)
            )
        ).all()
    )


async def _case_article_cards(session: AsyncSession, case_id: UUID) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(ArticleCard, Article.published_at)
            .join(Article, Article.id == ArticleCard.article_id)
            .join(CaseArticle, CaseArticle.article_id == Article.id)
            .where(CaseArticle.case_id == case_id)
            .order_by(Article.published_at.asc().nulls_last(), Article.created_at.asc())
        )
    ).all()
    return [
        {
            "title_uk": card.title_uk,
            "summary_uk": card.summary_uk,
            "published_at": published_at.isoformat() if published_at else None,
        }
        for card, published_at in rows
    ]


def _lifecycle_sample(cards: Sequence[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if len(cards) <= limit:
        return list(cards)
    selected = {0, len(cards) - 1}
    for index in range(1, limit - 1):
        selected.add(round(index * (len(cards) - 1) / (limit - 1)))
    return [cards[index] for index in sorted(selected)]
