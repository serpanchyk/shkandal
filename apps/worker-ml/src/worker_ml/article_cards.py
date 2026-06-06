"""Article-card LLM job handling."""

from __future__ import annotations

import json
from typing import Any, cast

from shkandal_database.jobs import ClaimedJob
from shkandal_database.models import Article, ArticleCard, ArticleRelevance, Source
from shkandal_database.session import async_session_scope
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from worker_ml.llm.contracts import ArticleCardOutput
from worker_ml.llm.runner import LlmTaskRunner

MAX_ARTICLE_TEXT_CHARACTERS = 20_000


class ArticleCardJobHandler:
    """Generate and persist a provisional article card."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        runner: LlmTaskRunner,
        *,
        model_name: str,
    ) -> None:
        self._session_factory = session_factory
        self._runner = runner
        self._model_name = model_name

    async def handle(self, job: ClaimedJob) -> ArticleCardOutput | None:
        """Generate a card for a relevant article unless one already exists."""

        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(Article, Source, ArticleRelevance.is_relevant, ArticleCard.id)
                    .join(Source, Source.id == Article.source_id)
                    .outerjoin(
                        ArticleRelevance,
                        ArticleRelevance.article_id == Article.id,
                    )
                    .outerjoin(ArticleCard, ArticleCard.article_id == Article.id)
                    .where(Article.id == job.article_id)
                )
            ).one_or_none()

        if row is None:
            raise ValueError(f"article not found for job {job.id}")
        article, source, is_relevant, article_card_id = row
        if not is_relevant or article_card_id is not None:
            return None

        result = await self._runner.run_with_provenance(
            run_type="article_card",
            model_name=self._model_name,
            variables={
                "article_json": build_article_json(article=article, source=source),
                "schema_json": json.dumps(
                    ArticleCardOutput.model_json_schema(),
                    ensure_ascii=False,
                ),
            },
            metadata={
                "article_id": str(job.article_id),
                "job_id": str(job.id),
            },
        )
        output = cast(ArticleCardOutput, result.output)

        async with async_session_scope(self._session_factory) as session:
            await session.execute(
                insert(ArticleCard)
                .values(
                    article_id=job.article_id,
                    llm_run_id=result.run_id,
                    title_uk=output.title_uk,
                    summary_uk=output.summary_uk,
                    card_json=output.model_dump(mode="json"),
                )
                .on_conflict_do_nothing(index_elements=[ArticleCard.article_id])
            )
        return output


def build_article_json(*, article: Article, source: Source) -> str:
    """Serialize compact source evidence for the article-card prompt."""

    payload: dict[str, Any] = {
        "title": article.title,
        "lead": article.lead,
        "url": article.url,
        "published_at": article.published_at.isoformat() if article.published_at else None,
        "source": {
            "name": source.name,
            "slug": source.slug,
            "source_type": source.source_type,
        },
        "extracted_text": (article.extracted_text or "")[:MAX_ARTICLE_TEXT_CHARACTERS],
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
