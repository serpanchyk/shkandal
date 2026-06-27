"""Reader-facing Case copy regeneration."""

import time
from collections.abc import Sequence
from typing import Any, cast
from uuid import UUID

from shkandal_database.jobs import ClaimedJob
from shkandal_database.models import Article, ArticleCard, Case, CaseArticle
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from worker_ml.cases.publication import (
    CaseMutationBusyError,
    case_vector_payload,
    try_case_mutation_lock,
)
from worker_ml.llm.budgeting import (
    count_metadata,
    json_dumps_compact,
    prompt_size_chars,
)
from worker_ml.llm.budgeting import (
    lifecycle_sample as budget_lifecycle_sample,
)
from worker_ml.llm.contracts import CaseCopyUpdateOutput
from worker_ml.llm.runner import LlmTaskRunner
from worker_ml.llm.schema import prompt_schema_json
from worker_ml.retrieval.vector_index import VectorIndexService

MAX_CASE_EVIDENCE_CARDS = 40


class CaseCopyUpdateJobHandler:
    """Regenerate stable reader-facing Case copy from accumulated evidence."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        runner: LlmTaskRunner,
        vector_index: VectorIndexService,
        *,
        model_name: str,
        card_limit: int = MAX_CASE_EVIDENCE_CARDS,
    ) -> None:
        self._session_factory = session_factory
        self._runner = runner
        self._vector_index = vector_index
        self._model_name = model_name
        self._card_limit = card_limit

    async def handle(self, job: ClaimedJob) -> CaseCopyUpdateOutput | None:
        """Update one Case and its vector under the global Case lock."""

        if job.case_id is None:
            raise ValueError("case-copy update job requires case_id")
        async with self._session_factory() as session:
            if not await try_case_mutation_lock(session):
                raise CaseMutationBusyError("case mutation lock is busy")
            case = await session.get(Case, job.case_id)
            if case is None:
                return None
            retrieval_started_at = time.monotonic()
            cards = await _case_article_cards(session, case.id)
            retrieval_duration_seconds = time.monotonic() - retrieval_started_at
            sampled_cards = lifecycle_sample(cards, self._card_limit)
            case_json = json_dumps_compact(
                {
                    "current_title_uk": case.title_uk,
                    "current_summary_uk": case.summary_uk,
                    "article_cards": sampled_cards,
                }
            )
            schema_json = prompt_schema_json(CaseCopyUpdateOutput)
            result = await self._runner.run_with_provenance(
                run_type="case_copy_update",
                model_name=self._model_name,
                variables={
                    "case_json": case_json,
                    "schema_json": schema_json,
                },
                metadata={
                    "case_id": str(case.id),
                    "job_id": str(job.id),
                    "retrieval_duration_seconds": round(retrieval_duration_seconds, 6),
                    **count_metadata(
                        prefix="article_card",
                        original_count=len(cards),
                        included_count=len(sampled_cards),
                    ),
                    "prompt_size_chars": prompt_size_chars(case_json, schema_json),
                },
            )
            output = cast(CaseCopyUpdateOutput, result.output)
            if output.title_action == "replace":
                case.title_uk = cast(str, output.replacement_title_uk)
            case.summary_uk = output.summary_uk
            await self._vector_index.upsert_case(case.id, case_vector_payload(case))
            await session.commit()
            return output


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


def lifecycle_sample(cards: Sequence[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Sample a Case lifecycle while preserving its first and latest evidence."""

    return budget_lifecycle_sample(cards, limit=limit)
