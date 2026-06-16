"""Production job-handler dependency assembly."""

from collections.abc import Callable, Iterator, Mapping
from typing import Protocol

from shkandal_database.jobs import ArticleJobStore, ClaimedJob
from shkandal_database.llm_cooldowns import LlmCooldownStore
from shkandal_vector_store import VectorStoreConfig, create_qdrant_client
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from worker_ml.articles.cards import ArticleCardJobHandler
from worker_ml.articles.relevance import ClassificationJobHandler, RelevanceModel
from worker_ml.cases.audits import CaseCoherenceAuditJobHandler
from worker_ml.cases.copy import CaseCopyUpdateJobHandler
from worker_ml.cases.resolution import ArticleCaseResolutionJobHandler
from worker_ml.cases.reviews import CaseDuplicateAuditJobHandler, CasePublicInterestAuditJobHandler
from worker_ml.config import MlConfig
from worker_ml.identities.resolution import (
    ArticleEntityResolutionJobHandler,
    ArticleEventResolutionJobHandler,
)
from worker_ml.llm.runner import LlmTaskRunner
from worker_ml.llm.runs import LlmRunStore
from worker_ml.retrieval.embeddings import E5Embedder
from worker_ml.retrieval.vector_index import VectorIndexService, create_vector_index_service
from worker_ml.runtime.planning import (
    AUDIT_CASE_COHERENCE_JOB,
    AUDIT_CASE_DUPLICATES_JOB,
    AUDIT_CASE_PUBLIC_INTEREST_JOB,
    CLASSIFY_ARTICLE_JOB,
    CREATE_ARTICLE_CARD_JOB,
    RESOLVE_ARTICLE_CASES_JOB,
    RESOLVE_ARTICLE_ENTITIES_JOB,
    RESOLVE_ARTICLE_EVENTS_JOB,
    UPDATE_CASE_COPY_JOB,
)


class JobHandler(Protocol):
    """Minimal interface for one supported ML job handler."""

    async def handle(self, job: ClaimedJob) -> object:
        """Process one claimed job."""


class _LazyJobHandlers(Mapping[str, JobHandler]):
    """Create heavyweight job handlers only when they are first needed."""

    def __init__(
        self,
        *,
        settings: MlConfig,
        session_factory: async_sessionmaker[AsyncSession],
        job_store: ArticleJobStore,
        model: RelevanceModel,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._job_store = job_store
        self._model = model
        self._run_store = LlmRunStore(session_factory)
        self._runner = LlmTaskRunner.from_config(
            settings=settings,
            run_store=self._run_store,
            cooldown_observer=LlmCooldownStore(session_factory),
        )
        self._vector_index: VectorIndexService | None = None
        self._handlers: dict[str, JobHandler] = {}
        self._factories: dict[str, Callable[[], JobHandler]] = {
            CLASSIFY_ARTICLE_JOB: self._create_classification_handler,
            CREATE_ARTICLE_CARD_JOB: self._create_article_card_handler,
            RESOLVE_ARTICLE_CASES_JOB: self._create_case_resolution_handler,
            RESOLVE_ARTICLE_ENTITIES_JOB: self._create_entity_resolution_handler,
            RESOLVE_ARTICLE_EVENTS_JOB: self._create_event_resolution_handler,
            UPDATE_CASE_COPY_JOB: self._create_case_copy_handler,
            AUDIT_CASE_COHERENCE_JOB: self._create_case_coherence_audit_handler,
            AUDIT_CASE_PUBLIC_INTEREST_JOB: self._create_case_public_interest_audit_handler,
            AUDIT_CASE_DUPLICATES_JOB: self._create_case_duplicate_audit_handler,
        }

    def __getitem__(self, key: str) -> JobHandler:
        handler = self._handlers.get(key)
        if handler is not None:
            return handler
        factory = self._factories[key]
        handler = factory()
        self._handlers[key] = handler
        return handler

    def __iter__(self) -> Iterator[str]:
        return iter(self._factories)

    def __len__(self) -> int:
        return len(self._factories)

    def _get_vector_index(self) -> VectorIndexService:
        if self._vector_index is None:
            embedder = E5Embedder.load(
                self._settings.embedding_model_dir,
                vector_size=self._settings.embedding_vector_size,
            )
            vector_config = VectorStoreConfig(
                qdrant_url=self._settings.qdrant_url,
                vector_size=self._settings.embedding_vector_size,
            )
            self._vector_index = create_vector_index_service(
                embedder=embedder,
                client=create_qdrant_client(vector_config),
                config=vector_config,
            )
        return self._vector_index

    def _create_classification_handler(self) -> JobHandler:
        return ClassificationJobHandler(self._session_factory, self._job_store, self._model)

    def _create_article_card_handler(self) -> JobHandler:
        return ArticleCardJobHandler(
            self._session_factory,
            self._runner,
            self._job_store,
            model_name=self._settings.llm_article_card_model,
        )

    def _create_case_resolution_handler(self) -> JobHandler:
        return ArticleCaseResolutionJobHandler(
            self._session_factory,
            self._job_store,
            self._runner,
            self._get_vector_index(),
            model_name=self._settings.llm_case_resolution_model,
            candidate_limit=self._settings.case_resolution_candidate_limit,
        )

    def _create_entity_resolution_handler(self) -> JobHandler:
        return ArticleEntityResolutionJobHandler(
            self._session_factory,
            self._runner,
            self._get_vector_index(),
            model_name=self._settings.llm_entity_resolution_model,
            candidate_limit=self._settings.entity_resolution_candidate_limit,
        )

    def _create_event_resolution_handler(self) -> JobHandler:
        return ArticleEventResolutionJobHandler(
            self._session_factory,
            self._runner,
            self._get_vector_index(),
            model_name=self._settings.llm_event_resolution_model,
            candidate_limit=self._settings.event_resolution_candidate_limit,
        )

    def _create_case_copy_handler(self) -> JobHandler:
        return CaseCopyUpdateJobHandler(
            self._session_factory,
            self._runner,
            self._get_vector_index(),
            model_name=self._settings.llm_case_copy_update_model,
        )

    def _create_case_coherence_audit_handler(self) -> JobHandler:
        return CaseCoherenceAuditJobHandler(
            self._session_factory,
            self._runner,
            self._get_vector_index(),
            job_store=self._job_store,
            model_name=self._settings.llm_case_coherence_audit_model,
            card_batch_size=self._settings.case_audit_card_batch_size,
        )

    def _create_case_public_interest_audit_handler(self) -> JobHandler:
        return CasePublicInterestAuditJobHandler(
            self._session_factory,
            self._runner,
            self._get_vector_index(),
            self._job_store,
            model_name=self._settings.llm_case_public_interest_audit_model,
        )

    def _create_case_duplicate_audit_handler(self) -> JobHandler:
        return CaseDuplicateAuditJobHandler(
            self._session_factory,
            self._runner,
            self._get_vector_index(),
            self._job_store,
            model_name=self._settings.llm_case_duplicate_audit_model,
        )


def create_handlers(
    *,
    settings: MlConfig,
    session_factory: async_sessionmaker[AsyncSession],
    job_store: ArticleJobStore,
    model: RelevanceModel,
) -> Mapping[str, JobHandler]:
    return _LazyJobHandlers(
        settings=settings,
        session_factory=session_factory,
        job_store=job_store,
        model=model,
    )
