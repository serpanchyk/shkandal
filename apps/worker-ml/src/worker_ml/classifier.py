"""Article relevance classification job handling."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol, cast

import joblib
from shkandal_database.jobs import ArticleJobStore, ClaimedJob
from shkandal_database.models import Article, ArticleRelevance
from shkandal_database.session import async_session_scope
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from worker_ml.jobs import CREATE_ARTICLE_CARD_JOB

POSITIVE_ARTIFACT_LABEL = "assigned"
NEGATIVE_ARTIFACT_LABEL = "noise"


class ProbabilityModel(Protocol):
    classes_: Any

    def predict_proba(self, texts: list[str]) -> Any:
        """Return class probabilities for input texts."""


@dataclass(frozen=True)
class RelevancePrediction:
    """Classifier output for one article."""

    is_relevant: bool
    score: Decimal
    metadata: dict[str, Any]


@dataclass(frozen=True)
class RelevanceModel:
    """Loaded relevance classifier and artifact metadata."""

    pipeline: ProbabilityModel
    classifier_name: str
    classifier_version: str
    threshold: float
    positive_class_index: int

    @classmethod
    def load(cls, model_dir: str | Path, *, threshold: float) -> RelevanceModel:
        """Load and validate the configured relevance classifier artifact."""

        root = Path(model_dir)
        manifest_path = root / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        pipeline_path = root / Path(manifest["artifact"]["pipeline_path"]).name
        pipeline = cast(ProbabilityModel, joblib.load(pipeline_path))
        classes = [str(label) for label in pipeline.classes_]
        if POSITIVE_ARTIFACT_LABEL not in classes:
            raise ValueError("relevance model does not expose assigned probability")
        if NEGATIVE_ARTIFACT_LABEL not in classes:
            raise ValueError("relevance model does not expose noise probability")

        return cls(
            pipeline=pipeline,
            classifier_name=root.name,
            classifier_version=str(manifest["created_at_utc"]),
            threshold=threshold,
            positive_class_index=classes.index(POSITIVE_ARTIFACT_LABEL),
        )

    def predict(self, *, title: str | None, extracted_text: str | None) -> RelevancePrediction:
        """Classify one article as a relevance candidate or irrelevant."""

        if not extracted_text or not extracted_text.strip():
            return RelevancePrediction(
                is_relevant=False,
                score=Decimal("0"),
                metadata={
                    "reason": "missing_extracted_text",
                    "threshold": self.threshold,
                    "positive_artifact_label": POSITIVE_ARTIFACT_LABEL,
                    "negative_artifact_label": NEGATIVE_ARTIFACT_LABEL,
                },
            )

        text = build_classifier_text(title=title, extracted_text=extracted_text)
        probabilities = self.pipeline.predict_proba([text])[0]
        score = float(probabilities[self.positive_class_index])
        return RelevancePrediction(
            is_relevant=score >= self.threshold,
            score=Decimal(str(score)),
            metadata={
                "threshold": self.threshold,
                "positive_artifact_label": POSITIVE_ARTIFACT_LABEL,
                "negative_artifact_label": NEGATIVE_ARTIFACT_LABEL,
            },
        )


class ClassificationJobHandler:
    """Execute article relevance classification jobs."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        job_store: ArticleJobStore,
        model: RelevanceModel,
    ) -> None:
        self._session_factory = session_factory
        self._job_store = job_store
        self._model = model

    async def handle(self, job: ClaimedJob) -> RelevancePrediction:
        """Classify the job article and persist classifier output."""

        async with self._session_factory() as session:
            article = await session.scalar(select(Article).where(Article.id == job.article_id))
            if article is None:
                raise ValueError(f"article not found for job {job.id}")
            prediction = self._model.predict(
                title=article.title,
                extracted_text=article.extracted_text,
            )

        decided_at = datetime.now(UTC)
        async with async_session_scope(self._session_factory) as session:
            statement = (
                insert(ArticleRelevance)
                .values(
                    article_id=job.article_id,
                    is_relevant=prediction.is_relevant,
                    score=prediction.score,
                    classifier_name=self._model.classifier_name,
                    classifier_version=self._model.classifier_version,
                    decided_at=decided_at,
                    metadata_=prediction.metadata,
                )
                .on_conflict_do_update(
                    index_elements=[ArticleRelevance.article_id],
                    set_={
                        "is_relevant": prediction.is_relevant,
                        "score": prediction.score,
                        "classifier_name": self._model.classifier_name,
                        "classifier_version": self._model.classifier_version,
                        "decided_at": decided_at,
                        "metadata": prediction.metadata,
                    },
                )
            )
            await session.execute(statement)

        if prediction.is_relevant:
            await self._job_store.enqueue_article_job(
                job_type=CREATE_ARTICLE_CARD_JOB,
                article_id=job.article_id,
                payload={"article_id": str(job.article_id)},
                max_attempts=job.max_attempts,
            )
        return prediction


def build_classifier_text(*, title: str | None, extracted_text: str) -> str:
    """Return text in the format used by the training notebook."""

    if title and title.strip():
        return f"{title.strip()}\n\n{extracted_text.strip()}"
    return extracted_text.strip()
