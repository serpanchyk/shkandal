"""Production job-handler dependency assembly."""

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
from worker_ml.retrieval.vector_index import create_vector_index_service
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


def create_handlers(
    *,
    settings: MlConfig,
    session_factory: async_sessionmaker[AsyncSession],
    job_store: ArticleJobStore,
    model: RelevanceModel,
) -> dict[str, JobHandler]:
    run_store = LlmRunStore(session_factory)
    runner = LlmTaskRunner.from_config(
        settings=settings,
        run_store=run_store,
        cooldown_observer=LlmCooldownStore(session_factory),
    )
    embedder = E5Embedder.load(
        settings.embedding_model_dir,
        vector_size=settings.embedding_vector_size,
    )
    vector_config = VectorStoreConfig(
        qdrant_url=settings.qdrant_url,
        vector_size=settings.embedding_vector_size,
    )
    vector_index = create_vector_index_service(
        embedder=embedder,
        client=create_qdrant_client(vector_config),
        config=vector_config,
    )
    return {
        CLASSIFY_ARTICLE_JOB: ClassificationJobHandler(session_factory, job_store, model),
        CREATE_ARTICLE_CARD_JOB: ArticleCardJobHandler(
            session_factory,
            runner,
            job_store,
            model_name=settings.llm_article_card_model,
        ),
        RESOLVE_ARTICLE_CASES_JOB: ArticleCaseResolutionJobHandler(
            session_factory,
            job_store,
            runner,
            vector_index,
            model_name=settings.llm_case_resolution_model,
            candidate_limit=settings.case_resolution_candidate_limit,
        ),
        RESOLVE_ARTICLE_ENTITIES_JOB: ArticleEntityResolutionJobHandler(
            session_factory,
            runner,
            vector_index,
            model_name=settings.llm_entity_resolution_model,
            candidate_limit=settings.entity_resolution_candidate_limit,
        ),
        RESOLVE_ARTICLE_EVENTS_JOB: ArticleEventResolutionJobHandler(
            session_factory,
            runner,
            vector_index,
            model_name=settings.llm_event_resolution_model,
            candidate_limit=settings.event_resolution_candidate_limit,
        ),
        UPDATE_CASE_COPY_JOB: CaseCopyUpdateJobHandler(
            session_factory,
            runner,
            vector_index,
            model_name=settings.llm_case_copy_update_model,
        ),
        AUDIT_CASE_COHERENCE_JOB: CaseCoherenceAuditJobHandler(
            session_factory,
            runner,
            vector_index,
            job_store=job_store,
            model_name=settings.llm_case_coherence_audit_model,
            card_batch_size=settings.case_audit_card_batch_size,
        ),
        AUDIT_CASE_PUBLIC_INTEREST_JOB: CasePublicInterestAuditJobHandler(
            session_factory,
            runner,
            vector_index,
            job_store,
            model_name=settings.llm_case_public_interest_audit_model,
        ),
        AUDIT_CASE_DUPLICATES_JOB: CaseDuplicateAuditJobHandler(
            session_factory,
            runner,
            vector_index,
            job_store,
            model_name=settings.llm_case_duplicate_audit_model,
        ),
    }
