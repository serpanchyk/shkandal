"""Article-case identity resolution and case-copy regeneration."""

from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

from shkandal_database.jobs import ArticleJobStore, ClaimedJob
from shkandal_database.models import Article, ArticleCard, Case, CaseArticle, Source
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from worker_ml.articles.cards import get_case_candidate_card
from worker_ml.cases.audits import load_case_article_cards
from worker_ml.cases.publication import (
    CaseMutationBusyError,
    case_vector_payload,
    try_case_mutation_lock,
)
from worker_ml.llm.budgeting import (
    compact_article_cards,
    count_metadata,
    first_latest_sample,
    json_dumps_compact,
    prompt_size_chars,
)
from worker_ml.llm.contracts import CaseLinkAuditOutput, CaseResolutionOutput
from worker_ml.llm.runner import LlmTaskRunner
from worker_ml.llm.schema import prompt_schema_json
from worker_ml.retrieval.vector_index import VectorIndexService
from worker_ml.runtime.planning import (
    RESOLVE_ARTICLE_ENTITIES_JOB,
    RESOLVE_ARTICLE_EVENTS_JOB,
    UPDATE_CASE_COPY_JOB,
)

CASE_CREATION_AFTER_DROPPED_LINKS_PROMPT = "case_creation_after_dropped_links"


@dataclass(frozen=True)
class RecheckedCaseResolution:
    """Resolution output after link audits, plus optional fallback provenance."""

    output: CaseResolutionOutput
    run_id: UUID | None


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
        candidate_limit: int,
        link_audit_card_limit: int = 20,
        representative_title_limit: int = 8,
    ) -> None:
        self._session_factory = session_factory
        self._job_store = job_store
        self._runner = runner
        self._vector_index = vector_index
        self._model_name = model_name
        self._candidate_limit = candidate_limit
        self._link_audit_card_limit = link_audit_card_limit
        self._representative_title_limit = representative_title_limit

    async def handle(self, job: ClaimedJob) -> CaseResolutionOutput | None:
        """Resolve and persist article-case identity under the global Case lock."""

        if job.article_id is None:
            raise ValueError("article-case resolution job requires article_id")
        async with self._session_factory() as session:
            if not await try_case_mutation_lock(session):
                raise CaseMutationBusyError("case mutation lock is busy")
            card = await get_case_candidate_card(session, article_id=job.article_id)
            if card is None:
                return None
            existing_case_ids = set(
                (
                    await session.scalars(
                        select(CaseArticle.case_id).where(CaseArticle.article_id == job.article_id)
                    )
                ).all()
            )
            if existing_case_ids:
                await _enqueue_resolution_followups(
                    job_store=self._job_store,
                    job=job,
                    case_ids=existing_case_ids,
                )
                return None
            article_row = (
                await session.execute(
                    select(Article, Source)
                    .join(Source, Source.id == Article.source_id)
                    .where(Article.id == job.article_id)
                )
            ).one()
            article, source = article_row
            retrieval_started_at = time.monotonic()
            candidates = await self._load_candidates(session, card)
            retrieval_duration_seconds = time.monotonic() - retrieval_started_at
            resolution_json = _resolution_json(article, source, card, candidates)
            schema_json = prompt_schema_json(CaseResolutionOutput)
            result = await self._runner.run_with_provenance(
                run_type="case_resolution",
                model_name=self._model_name,
                variables={
                    "resolution_json": resolution_json,
                    "schema_json": schema_json,
                },
                metadata={
                    "article_id": str(job.article_id),
                    "job_id": str(job.id),
                    "retrieval_duration_seconds": round(retrieval_duration_seconds, 6),
                    "retrieved_candidate_count": len(candidates),
                    "prompt_size_chars": prompt_size_chars(resolution_json, schema_json),
                },
            )
            output = cast(CaseResolutionOutput, result.output)
            candidate_ids = {candidate["case_id"] for candidate in candidates}
            if output.outcome == "rejected":
                return output
            rechecked = await self._recheck_existing_case_links_for_resolution(
                session,
                job=job,
                article=article,
                source=source,
                card=card,
                output=output,
                candidates=candidates,
                initial_run_id=result.run_id,
            )
            output = rechecked.output
            if output.outcome == "rejected":
                return output
            affected_case_ids = await self._persist_resolution(
                session,
                article=article,
                output=output,
                run_id=rechecked.run_id,
                candidate_ids=candidate_ids,
            )
            for case_id in affected_case_ids:
                case = await session.get(Case, case_id)
                if case is not None:
                    await self._vector_index.upsert_case(case.id, case_vector_payload(case))
            await session.commit()

        await _enqueue_resolution_followups(
            job_store=self._job_store,
            job=job,
            case_ids=affected_case_ids,
        )
        return output

    async def _load_candidates(
        self, session: AsyncSession, card: ArticleCard
    ) -> list[dict[str, Any]]:
        results = await self._vector_index.search_cases(
            _article_card_query(card), limit=self._candidate_limit
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
        evidence_titles = await _representative_article_titles_by_case(
            session,
            set(by_id),
            limit=self._representative_title_limit,
        )
        return [
            {
                "case_id": str(result.id),
                "score": result.score,
                "title_uk": by_id[result.id].title_uk,
                "summary_uk": by_id[result.id].summary_uk,
                "evidence_titles": evidence_titles.get(result.id, []),
            }
            for result in results
            if result.id in by_id
        ]

    async def _recheck_existing_case_links(
        self,
        session: AsyncSession,
        *,
        job: ClaimedJob,
        article: Article,
        card: ArticleCard,
        output: CaseResolutionOutput,
        candidates: list[dict[str, Any]],
    ) -> CaseResolutionOutput:
        result = await self._recheck_existing_case_links_for_resolution(
            session,
            job=job,
            article=article,
            source=None,
            card=card,
            output=output,
            candidates=candidates,
            initial_run_id=None,
        )
        return result.output

    async def _recheck_existing_case_links_for_resolution(
        self,
        session: AsyncSession,
        *,
        job: ClaimedJob,
        article: Article,
        source: Source | None,
        card: ArticleCard,
        output: CaseResolutionOutput,
        candidates: list[dict[str, Any]],
        initial_run_id: UUID | None,
    ) -> RecheckedCaseResolution:
        if not output.existing_case_links:
            return RecheckedCaseResolution(output=output, run_id=initial_run_id)
        candidate_by_id = {candidate["case_id"]: candidate for candidate in candidates}
        kept_case_ids: set[str] = set()
        rechecked_links = []
        dropped_link_audits: list[dict[str, Any]] = []
        for link in output.existing_case_links:
            case_id = UUID(link.case_id)
            case = await session.get(Case, case_id)
            if case is None or case.status != "active":
                dropped_link_audits.append(
                    {
                        "case_id": link.case_id,
                        "link_reason_uk": link.link_reason_uk,
                        "confidence": link.confidence,
                        "audit_outcome": "drop",
                        "audit_reason_uk": "Candidate case is missing or inactive.",
                        "candidate": candidate_by_id.get(link.case_id),
                    }
                )
                continue
            linked_cards = await load_case_article_cards(session, case_id)
            decision = await self._run_case_link_audit(
                job=job,
                article=article,
                card=card,
                case=case,
                candidate=candidate_by_id[link.case_id],
                linked_cards=linked_cards,
            )
            if decision.outcome != "connect":
                dropped_link_audits.append(
                    {
                        "case_id": link.case_id,
                        "link_reason_uk": link.link_reason_uk,
                        "confidence": link.confidence,
                        "audit_outcome": decision.outcome,
                        "audit_reason_uk": decision.reason_uk,
                        "audit_diagnosis": decision.diagnosis.model_dump(mode="json"),
                        "candidate": candidate_by_id[link.case_id],
                    }
                )
                continue
            kept_case_ids.add(link.case_id)
            rechecked_links.append(link)
        filtered = output.model_copy(update={"existing_case_links": rechecked_links})
        if filtered.existing_case_links or filtered.new_cases:
            return RecheckedCaseResolution(output=filtered, run_id=initial_run_id)
        if source is not None:
            fallback = await self._run_new_case_fallback_after_dropped_links(
                job=job,
                article=article,
                source=source,
                card=card,
                output=output,
                candidates=candidates,
                dropped_link_audits=dropped_link_audits,
            )
            if fallback.output.outcome == "resolved":
                return fallback
            return RecheckedCaseResolution(output=fallback.output, run_id=fallback.run_id)
        return RecheckedCaseResolution(
            output=_reject_resolution_after_link_audit(output),
            run_id=initial_run_id,
        )

    async def _run_new_case_fallback_after_dropped_links(
        self,
        *,
        job: ClaimedJob,
        article: Article,
        source: Source,
        card: ArticleCard,
        output: CaseResolutionOutput,
        candidates: list[dict[str, Any]],
        dropped_link_audits: list[dict[str, Any]],
    ) -> RecheckedCaseResolution:
        resolution_json = _dropped_link_fallback_json(
            article=article,
            source=source,
            card=card,
            original_output=output,
            candidates=candidates,
            dropped_link_audits=dropped_link_audits,
        )
        schema_json = prompt_schema_json(CaseResolutionOutput)
        result = await self._runner.run_with_provenance(
            run_type="case_resolution",
            prompt_name=CASE_CREATION_AFTER_DROPPED_LINKS_PROMPT,
            model_name=self._model_name,
            variables={
                "resolution_json": resolution_json,
                "schema_json": schema_json,
            },
            metadata={
                "article_id": str(article.id),
                "job_id": str(job.id),
                "fallback_reason": "all_existing_case_links_dropped",
                "dropped_existing_link_count": len(dropped_link_audits),
                "prompt_size_chars": prompt_size_chars(resolution_json, schema_json),
            },
        )
        fallback_output = cast(CaseResolutionOutput, result.output)
        _validate_dropped_link_fallback_output(fallback_output)
        return RecheckedCaseResolution(output=fallback_output, run_id=result.run_id)

    async def _run_case_link_audit(
        self,
        *,
        job: ClaimedJob,
        article: Article,
        card: ArticleCard,
        case: Case,
        candidate: dict[str, Any],
        linked_cards: list[dict[str, Any]],
    ) -> CaseLinkAuditOutput:
        audited_cards = first_latest_sample(
            compact_article_cards(linked_cards),
            limit=self._link_audit_card_limit,
        )
        case_json = json_dumps_compact(
            {
                "article": {
                    "article_id": str(article.id),
                    "published_at": article.published_at.isoformat()
                    if article.published_at
                    else None,
                    "card": {
                        "title_uk": card.title_uk,
                        "summary_uk": card.summary_uk,
                        **card.card_json,
                    },
                },
                "case": {
                    "case_id": str(case.id),
                    "title_uk": case.title_uk,
                    "summary_uk": case.summary_uk,
                    "candidate_score": candidate["score"],
                    "evidence_titles": candidate["evidence_titles"],
                    "article_cards": audited_cards,
                },
            }
        )
        schema_json = prompt_schema_json(CaseLinkAuditOutput)
        result = await self._runner.run_with_provenance(
            run_type="case_link_audit",
            model_name=self._model_name,
            variables={
                "case_json": case_json,
                "schema_json": schema_json,
            },
            metadata={
                "article_id": str(article.id),
                "case_id": str(case.id),
                "job_id": str(job.id),
                **count_metadata(
                    prefix="linked_article",
                    original_count=len(linked_cards),
                    included_count=len(audited_cards),
                ),
                "prompt_size_chars": prompt_size_chars(case_json, schema_json),
            },
        )
        return cast(CaseLinkAuditOutput, result.output)

    async def _persist_resolution(
        self,
        session: AsyncSession,
        *,
        article: Article,
        output: CaseResolutionOutput,
        run_id: UUID | None,
        candidate_ids: set[str],
    ) -> set[UUID]:
        affected: set[UUID] = set()
        published_at = article.published_at
        for link in output.existing_case_links:
            if link.case_id not in candidate_ids:
                raise ValueError(f"existing link references non-candidate case: {link.case_id}")
            case_id = UUID(link.case_id)
            affected.add(case_id)
            inserted_id = await session.scalar(
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
                .returning(CaseArticle.id)
            )
            if inserted_id is not None:
                await session.execute(
                    update(Case)
                    .where(Case.id == case_id)
                    .values(
                        article_count=Case.article_count + 1,
                        evidence_revision=Case.evidence_revision + 1,
                        last_updated_at=(
                            func.greatest(Case.last_updated_at, published_at)
                            if published_at is not None
                            else Case.last_updated_at
                        ),
                    )
                )
        for decision in output.new_cases:
            case_id = uuid4()
            affected.add(case_id)
            session.add(
                Case(
                    id=case_id,
                    slug=f"case-{case_id.hex}",
                    title_uk=decision.title_uk,
                    summary_uk=decision.summary_uk,
                    status="active",
                    first_seen_at=published_at,
                    last_updated_at=published_at,
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
        return affected


def _reject_resolution_after_link_audit(output: CaseResolutionOutput) -> CaseResolutionOutput:
    """Rewrite a linkless resolution into an explicit rejection."""

    diagnosis = output.diagnosis.model_copy(
        update={
            "matching_existing_case_ids": [],
            "rejection_signals_uk": [
                *output.diagnosis.rejection_signals_uk,
                "Жодна наявна справа не підтвердила прив'язку після повторної перевірки.",
            ],
        }
    )
    return CaseResolutionOutput.model_validate(
        {
            "diagnosis": diagnosis.model_dump(mode="json"),
            "existing_case_links": [],
            "new_cases": [],
            "decision_reason_uk": (
                "Повторна перевірка не підтвердила безпечну прив'язку "
                "статті до жодної наявної справи."
            ),
            "outcome": "rejected",
        }
    )


async def _enqueue_resolution_followups(
    *,
    job_store: ArticleJobStore,
    job: ClaimedJob,
    case_ids: set[UUID],
) -> None:
    if job.article_id is None:
        raise ValueError("article-case resolution follow-ups require article_id")
    for case_id in case_ids:
        await job_store.enqueue_case_job(
            job_type=UPDATE_CASE_COPY_JOB,
            case_id=case_id,
            payload={"case_id": str(case_id)},
            max_attempts=job.max_attempts,
        )
    for job_type in (RESOLVE_ARTICLE_ENTITIES_JOB, RESOLVE_ARTICLE_EVENTS_JOB):
        await job_store.enqueue_article_job(
            job_type=job_type,
            article_id=job.article_id,
            payload={"article_id": str(job.article_id)},
            max_attempts=job.max_attempts,
        )


def _article_card_query(card: ArticleCard) -> str:
    values = [card.title_uk, card.summary_uk, *card.card_json.get("case_signature_terms", [])]
    return "\n".join(str(value) for value in values if value)


def _resolution_json(
    article: Article, source: Source, card: ArticleCard, candidates: list[dict[str, Any]]
) -> str:
    return json_dumps_compact(
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
        }
    )


def _dropped_link_fallback_json(
    *,
    article: Article,
    source: Source,
    card: ArticleCard,
    original_output: CaseResolutionOutput,
    candidates: list[dict[str, Any]],
    dropped_link_audits: list[dict[str, Any]],
) -> str:
    return json_dumps_compact(
        {
            "article": {
                "article_id": str(article.id),
                "source_title": article.title,
                "url": article.url,
                "published_at": article.published_at.isoformat() if article.published_at else None,
                "source_name": source.name,
                "source_slug": source.slug,
                "card": {
                    "title_uk": card.title_uk,
                    "summary_uk": card.summary_uk,
                    **card.card_json,
                },
            },
            "original_case_resolution": {
                "diagnosis": original_output.diagnosis.model_dump(mode="json"),
                "decision_reason_uk": original_output.decision_reason_uk,
                "existing_case_links": [
                    link.model_dump(mode="json") for link in original_output.existing_case_links
                ],
                "new_cases": [
                    decision.model_dump(mode="json") for decision in original_output.new_cases
                ],
            },
            "rejected_candidate_cases": candidates,
            "case_link_audit_outcomes": dropped_link_audits,
            "fallback_instruction": (
                "All proposed existing links were dropped by case_link_audit. "
                "Create only genuinely new cases, or reject."
            ),
        }
    )


def _validate_dropped_link_fallback_output(output: CaseResolutionOutput) -> None:
    if output.existing_case_links:
        raise ValueError("dropped-link fallback cannot return existing case links")
    if output.outcome == "resolved" and not output.new_cases:
        raise ValueError("dropped-link fallback resolution must create a new case")


async def _representative_article_titles_by_case(
    session: AsyncSession,
    case_ids: set[UUID],
    *,
    limit: int,
) -> dict[UUID, list[str]]:
    if not case_ids:
        return {}
    rank = (
        func.row_number()
        .over(
            partition_by=CaseArticle.case_id,
            order_by=(Article.published_at.asc().nulls_last(), Article.created_at.asc()),
        )
        .label("position")
    )
    ranked = (
        select(CaseArticle.case_id, ArticleCard.title_uk, rank)
        .join(Article, Article.id == CaseArticle.article_id)
        .join(ArticleCard, ArticleCard.article_id == Article.id)
        .where(CaseArticle.case_id.in_(case_ids))
        .subquery()
    )
    rows = (
        await session.execute(
            select(ranked.c.case_id, ranked.c.title_uk)
            .where(ranked.c.position <= limit)
            .order_by(ranked.c.case_id, ranked.c.position)
        )
    ).all()
    grouped: dict[UUID, list[str]] = {case_id: [] for case_id in case_ids}
    for case_id, title in rows:
        grouped[case_id].append(title)
    return grouped
