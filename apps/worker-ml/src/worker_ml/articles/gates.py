"""Article-gate LLM job handling."""

from __future__ import annotations

from typing import cast

from shkandal_database.jobs import ArticleJobStore, ClaimedJob
from shkandal_database.models import (
    Article,
    ArticleCard,
    ArticleGateDecision,
    ArticleRelevance,
    Source,
)
from shkandal_database.session import async_session_scope
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from worker_ml.articles.cards import build_article_json_with_budget
from worker_ml.llm.budgeting import prompt_size_chars
from worker_ml.llm.contracts import ArticleGateOutput
from worker_ml.llm.runner import LlmTaskRunner
from worker_ml.llm.schema import prompt_schema_json
from worker_ml.runtime.planning import CREATE_ARTICLE_CARD_JOB


class ArticleGateJobHandler:
    """Generate and persist the second-layer relevance gate for an article."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        runner: LlmTaskRunner,
        job_store: ArticleJobStore,
        *,
        model_name: str,
        text_max_chars: int,
    ) -> None:
        self._session_factory = session_factory
        self._runner = runner
        self._job_store = job_store
        self._model_name = model_name
        self._text_max_chars = text_max_chars

    async def handle(self, job: ClaimedJob) -> ArticleGateOutput | None:
        """Gate a classifier-relevant article unless a gate decision already exists."""

        if job.article_id is None:
            raise ValueError("article-gate job requires article_id")
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(
                        Article,
                        Source,
                        ArticleRelevance.is_relevant,
                        ArticleGateDecision.id,
                        ArticleCard.id,
                    )
                    .join(Source, Source.id == Article.source_id)
                    .outerjoin(ArticleRelevance, ArticleRelevance.article_id == Article.id)
                    .outerjoin(ArticleGateDecision, ArticleGateDecision.article_id == Article.id)
                    .outerjoin(ArticleCard, ArticleCard.article_id == Article.id)
                    .where(Article.id == job.article_id)
                )
            ).one_or_none()

        if row is None:
            raise ValueError(f"article not found for job {job.id}")
        article, source, is_relevant, gate_decision_id, article_card_id = row
        if not is_relevant or gate_decision_id is not None:
            return None

        article_json, budget = build_article_json_with_budget(
            article=article,
            source=source,
            text_max_chars=self._text_max_chars,
        )
        schema_json = prompt_schema_json(ArticleGateOutput)
        result = await self._runner.run_with_provenance(
            run_type="article_gate",
            model_name=self._model_name,
            variables={
                "article_json": article_json,
                "schema_json": schema_json,
            },
            metadata={
                "article_id": str(job.article_id),
                "job_id": str(job.id),
                "article_text_chars": budget.original_chars,
                "included_article_text_chars": budget.included_chars,
                "input_truncated": budget.truncated,
                "prompt_size_chars": prompt_size_chars(article_json, schema_json),
            },
        )
        output = cast(ArticleGateOutput, result.output)

        async with async_session_scope(self._session_factory) as session:
            await session.execute(
                insert(ArticleGateDecision)
                .values(
                    article_id=job.article_id,
                    llm_run_id=result.run_id,
                    is_case_candidate=output.is_case_candidate,
                    noise_reason=output.noise_reason,
                    case_diagnosis=output.case_diagnosis.model_dump(mode="json"),
                    case_decision_reason_uk=output.case_decision_reason_uk,
                    metadata_={},
                )
                .on_conflict_do_nothing(index_elements=[ArticleGateDecision.article_id])
            )
        if output.is_case_candidate and article_card_id is None:
            await self._job_store.enqueue_article_job(
                job_type=CREATE_ARTICLE_CARD_JOB,
                article_id=job.article_id,
                payload={"article_id": str(job.article_id)},
                max_attempts=job.max_attempts,
            )
        return output
