"""ML worker process entrypoint."""

import argparse
import asyncio
import logging
import time
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Protocol

from shkandal_common.logging import setup_logger
from shkandal_database.config import DatabaseConfig
from shkandal_database.jobs import ArticleJobStore, ClaimedJob, JobQueueSummary
from shkandal_database.llm_cooldowns import LlmCooldownStore
from shkandal_database.session import create_async_engine_from_config, create_async_sessionmaker
from shkandal_vector_store import VectorStoreConfig, create_qdrant_client
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from worker_ml.article_cards import ArticleCardJobHandler
from worker_ml.case_audits import CaseAuditSupersededError, CaseCoherenceAuditJobHandler
from worker_ml.case_resolution import (
    ArticleCaseResolutionJobHandler,
    CaseCopyUpdateJobHandler,
    CaseMutationBusyError,
)
from worker_ml.classifier import ClassificationJobHandler, RelevanceModel
from worker_ml.config import MlConfig
from worker_ml.embeddings import E5Embedder
from worker_ml.identity_resolution import (
    ArticleEntityResolutionJobHandler,
    ArticleEventResolutionJobHandler,
    IdentityMutationBusyError,
)
from worker_ml.jobs import (
    AUDIT_CASE_COHERENCE_JOB,
    CLASSIFY_ARTICLE_JOB,
    CREATE_ARTICLE_CARD_JOB,
    RESOLVE_ARTICLE_CASES_JOB,
    RESOLVE_ARTICLE_ENTITIES_JOB,
    RESOLVE_ARTICLE_EVENTS_JOB,
    UPDATE_CASE_COPY_JOB,
    EnqueueStats,
    MlJobPlanner,
)
from worker_ml.llm.runner import LlmRateLimitError, LlmTaskRunner
from worker_ml.llm.runs import LlmRunStore
from worker_ml.vector_index import create_vector_index_service

SUPPORTED_JOB_TYPES = (
    CLASSIFY_ARTICLE_JOB,
    CREATE_ARTICLE_CARD_JOB,
    RESOLVE_ARTICLE_CASES_JOB,
    RESOLVE_ARTICLE_ENTITIES_JOB,
    RESOLVE_ARTICLE_EVENTS_JOB,
    UPDATE_CASE_COPY_JOB,
    AUDIT_CASE_COHERENCE_JOB,
)
JOB_TYPE_SCHEDULE = (
    CREATE_ARTICLE_CARD_JOB,
    UPDATE_CASE_COPY_JOB,
    AUDIT_CASE_COHERENCE_JOB,
    RESOLVE_ARTICLE_CASES_JOB,
    RESOLVE_ARTICLE_ENTITIES_JOB,
    RESOLVE_ARTICLE_EVENTS_JOB,
    CLASSIFY_ARTICLE_JOB,
)


class JobHandler(Protocol):
    """Minimal interface for one supported ML job handler."""

    async def handle(self, job: ClaimedJob) -> object:
        """Process one claimed job."""


async def run_once(config: MlConfig | None = None) -> dict[str, int | float]:
    """Enqueue and process one bounded batch of ML jobs."""

    settings = config or MlConfig()
    logger = setup_logger(settings.service_name)
    engine = create_async_engine_from_config(
        DatabaseConfig(database_url=settings.postgres_database_url)
    )
    try:
        session_factory = create_async_sessionmaker(engine)
        cooldown_store = LlmCooldownStore(session_factory)
        if await _log_active_cooldown(cooldown_store=cooldown_store, logger=logger):
            return _empty_cycle_stats()
        model = RelevanceModel.load(
            settings.relevance_model_dir,
            threshold=settings.relevance_threshold,
        )
        job_store = ArticleJobStore(
            session_factory,
            stale_job_timeout=settings.stale_job_timeout,
        )
        planner = MlJobPlanner(session_factory, job_store)
        handlers = _create_handlers(
            settings=settings,
            session_factory=session_factory,
            job_store=job_store,
            model=model,
        )
        await _cleanup_stale_llm_runs(
            settings=settings,
            logger=logger,
            run_store=LlmRunStore(session_factory),
        )
        return await _run_cycle(
            settings=settings,
            logger=logger,
            planner=planner,
            job_store=job_store,
            cooldown_store=cooldown_store,
            handlers=handlers,
        )
    finally:
        await engine.dispose()


async def enqueue_missing_classification_jobs(config: MlConfig | None = None) -> dict[str, int]:
    """Run one ML enqueue pass for articles missing classifier output."""

    settings = config or MlConfig()
    logger = setup_logger(settings.service_name)
    engine = create_async_engine_from_config(
        DatabaseConfig(database_url=settings.postgres_database_url)
    )
    try:
        session_factory = create_async_sessionmaker(engine)
        job_store = ArticleJobStore(
            session_factory,
            stale_job_timeout=settings.stale_job_timeout,
        )
        planner = MlJobPlanner(session_factory, job_store)
        stats = await planner.enqueue_missing_classification_jobs(
            limit=settings.enqueue_batch_size,
            max_attempts=settings.job_max_attempts,
        )
        logger.info(
            "worker_ml_jobs_enqueued",
            extra={
                "scanned_articles": stats.scanned_articles,
                "ensured_jobs": stats.ensured_jobs,
                "inserted_jobs": stats.inserted_jobs,
                "requeued_jobs": stats.requeued_jobs,
                "existing_jobs": stats.existing_jobs,
                "job_type": "classify_article",
            },
        )
        return {
            "scanned_articles": stats.scanned_articles,
            "ensured_jobs": stats.ensured_jobs,
            "inserted_jobs": stats.inserted_jobs,
            "requeued_jobs": stats.requeued_jobs,
            "existing_jobs": stats.existing_jobs,
        }
    finally:
        await engine.dispose()


async def process_next_job(
    config: MlConfig | None = None,
    *,
    worker_id: str | None = None,
) -> dict[str, str]:
    """Claim and process one supported ML job."""

    settings = config or MlConfig()
    logger = setup_logger(settings.service_name)
    engine = create_async_engine_from_config(
        DatabaseConfig(database_url=settings.postgres_database_url)
    )
    try:
        session_factory = create_async_sessionmaker(engine)
        job_store = ArticleJobStore(
            session_factory,
            stale_job_timeout=settings.stale_job_timeout,
        )
        cooldown_store = LlmCooldownStore(session_factory)
        if await _log_active_cooldown(cooldown_store=cooldown_store, logger=logger):
            return {"status": "idle"}
        claimed_job = await job_store.claim_next_job(
            worker_id=worker_id or settings.service_name,
            job_types=SUPPORTED_JOB_TYPES,
        )
        if claimed_job is None:
            return {"status": "idle"}

        model = RelevanceModel.load(
            settings.relevance_model_dir,
            threshold=settings.relevance_threshold,
        )
        handlers = _create_handlers(
            settings=settings,
            session_factory=session_factory,
            job_store=job_store,
            model=model,
        )
        await _cleanup_stale_llm_runs(
            settings=settings,
            logger=logger,
            run_store=LlmRunStore(session_factory),
        )
        try:
            await handlers[claimed_job.job_type].handle(claimed_job)
        except LlmRateLimitError as exc:
            resume_at = await _defer_for_rate_limit(
                job=claimed_job,
                error=exc,
                job_store=job_store,
                cooldown_store=cooldown_store,
            )
            logger.warning(
                "worker_ml_llm_rate_limited",
                extra={
                    "job_id": str(claimed_job.id),
                    "job_type": claimed_job.job_type,
                    "resume_at": resume_at.isoformat(),
                },
            )
            return {"status": "deferred", "job_type": claimed_job.job_type}
        except (CaseAuditSupersededError, CaseMutationBusyError, IdentityMutationBusyError) as exc:
            await job_store.defer_job(
                job_id=claimed_job.id,
                run_after=datetime.now(UTC) + timedelta(seconds=10),
                reason=str(exc),
            )
            return {"status": "deferred", "job_type": claimed_job.job_type}
        except Exception as exc:
            await job_store.fail_job(
                job_id=claimed_job.id,
                error_message=_exception_message(exc),
                attempt_count=claimed_job.attempt_count,
                max_attempts=claimed_job.max_attempts,
                processed_revision=_processed_revision(claimed_job),
            )
            logger.exception(
                "worker_ml_job_failed",
                extra={
                    "job_id": str(claimed_job.id),
                    "job_type": claimed_job.job_type,
                    "article_id": str(claimed_job.article_id),
                },
            )
            return {"status": "failed", "job_type": claimed_job.job_type}

        await job_store.complete_job(
            job_id=claimed_job.id,
            processed_revision=_processed_revision(claimed_job),
        )
        logger.info(
            "worker_ml_job_succeeded",
            extra={
                "job_id": str(claimed_job.id),
                "job_type": claimed_job.job_type,
                "article_id": str(claimed_job.article_id),
            },
        )
        return {"status": "succeeded", "job_type": claimed_job.job_type}
    finally:
        await engine.dispose()


async def run_worker(config: MlConfig | None = None) -> None:
    """Poll for article classification work until the process is stopped."""

    settings = config or MlConfig()
    logger = setup_logger(settings.service_name)
    engine = create_async_engine_from_config(
        DatabaseConfig(database_url=settings.postgres_database_url)
    )
    try:
        session_factory = create_async_sessionmaker(engine)
        cooldown_store = LlmCooldownStore(session_factory)
        if await _log_active_cooldown(cooldown_store=cooldown_store, logger=logger):
            return
        model = RelevanceModel.load(
            settings.relevance_model_dir,
            threshold=settings.relevance_threshold,
        )
        job_store = ArticleJobStore(
            session_factory,
            stale_job_timeout=settings.stale_job_timeout,
        )
        planner = MlJobPlanner(session_factory, job_store)
        handlers = _create_handlers(
            settings=settings,
            session_factory=session_factory,
            job_store=job_store,
            model=model,
        )
        await _cleanup_stale_llm_runs(
            settings=settings,
            logger=logger,
            run_store=LlmRunStore(session_factory),
        )
        logger.info(
            "worker_ml_started",
            extra={
                "service": settings.service_name,
                "poll_interval_seconds": settings.poll_interval_seconds,
                "enqueue_batch_size": settings.enqueue_batch_size,
                "claim_batch_size": settings.claim_batch_size,
                "worker_concurrency": settings.worker_concurrency,
                "relevance_model_dir": settings.relevance_model_dir,
            },
        )

        while True:
            stats = await _run_cycle(
                settings=settings,
                logger=logger,
                planner=planner,
                job_store=job_store,
                cooldown_store=cooldown_store,
                handlers=handlers,
            )
            if stats["processed_jobs"] == 0 and stats["ensured_jobs"] == 0:
                await asyncio.sleep(settings.poll_interval_seconds)
    finally:
        await engine.dispose()


async def run_backfill(config: MlConfig | None = None) -> JobQueueSummary:
    """Drain all current and newly-created ML jobs, then exit."""

    settings = config or MlConfig()
    logger = setup_logger(settings.service_name)
    engine = create_async_engine_from_config(
        DatabaseConfig(database_url=settings.postgres_database_url)
    )
    try:
        session_factory = create_async_sessionmaker(engine)
        cooldown_store = LlmCooldownStore(session_factory)
        model = RelevanceModel.load(
            settings.relevance_model_dir,
            threshold=settings.relevance_threshold,
        )
        job_store = ArticleJobStore(
            session_factory,
            stale_job_timeout=settings.stale_job_timeout,
        )
        planner = MlJobPlanner(session_factory, job_store)
        handlers = _create_handlers(
            settings=settings,
            session_factory=session_factory,
            job_store=job_store,
            model=model,
        )
        await _cleanup_stale_llm_runs(
            settings=settings,
            logger=logger,
            run_store=LlmRunStore(session_factory),
        )
        logger.info(
            "worker_ml_backfill_started",
            extra={
                "service": settings.service_name,
                "poll_interval_seconds": settings.poll_interval_seconds,
                "enqueue_batch_size": settings.enqueue_batch_size,
                "claim_batch_size": settings.claim_batch_size,
                "worker_concurrency": settings.worker_concurrency,
            },
        )
        return await _drain_backfill(
            settings=settings,
            logger=logger,
            planner=planner,
            job_store=job_store,
            cooldown_store=cooldown_store,
            handlers=handlers,
        )
    finally:
        await engine.dispose()


async def _drain_backfill(
    *,
    settings: MlConfig,
    logger: logging.Logger,
    planner: MlJobPlanner,
    job_store: ArticleJobStore,
    cooldown_store: LlmCooldownStore,
    handlers: Mapping[str, JobHandler],
) -> JobQueueSummary:
    while True:
        if await _log_active_cooldown(cooldown_store=cooldown_store, logger=logger):
            await asyncio.sleep(settings.poll_interval_seconds)
            continue
        stats = await _run_cycle(
            settings=settings,
            logger=logger,
            planner=planner,
            job_store=job_store,
            cooldown_store=cooldown_store,
            handlers=handlers,
            requeue_failed=False,
        )
        summary = await job_store.summarize_jobs(job_types=SUPPORTED_JOB_TYPES)
        active_running_jobs = summary.running_jobs - summary.blocked_running_jobs
        if summary.queued_jobs == 0 and active_running_jobs == 0:
            logger.info(
                "worker_ml_backfill_finished",
                extra={
                    "failed_jobs": summary.failed_jobs,
                    "blocked_jobs": summary.blocked_jobs,
                },
            )
            return summary
        if stats["processed_jobs"] == 0 and stats["ensured_jobs"] == 0:
            logger.info(
                "worker_ml_backfill_waiting",
                extra={
                    "queued_jobs": summary.queued_jobs,
                    "running_jobs": active_running_jobs,
                    "blocked_jobs": summary.blocked_jobs,
                    "next_run_after": (
                        summary.next_run_after.isoformat()
                        if summary.next_run_after is not None
                        else None
                    ),
                },
            )
            await asyncio.sleep(settings.poll_interval_seconds)


async def _run_cycle(
    *,
    settings: MlConfig,
    logger: logging.Logger,
    planner: MlJobPlanner,
    job_store: ArticleJobStore,
    cooldown_store: LlmCooldownStore,
    handlers: Mapping[str, JobHandler],
    requeue_failed: bool = True,
) -> dict[str, int | float]:
    cycle_started_at = time.monotonic()
    if await _log_active_cooldown(cooldown_store=cooldown_store, logger=logger):
        return _empty_cycle_stats()

    enqueue_stats = await planner.enqueue_missing_classification_jobs(
        limit=settings.enqueue_batch_size,
        max_attempts=settings.job_max_attempts,
        requeue_failed=requeue_failed,
    )
    audit_stats = (
        await planner.enqueue_due_case_audit_jobs(
            limit=settings.case_audit_enqueue_batch_size,
            max_attempts=settings.job_max_attempts,
            interval_days=settings.case_audit_interval_days,
        )
        if settings.case_audit_automatic_enabled
        else EnqueueStats(0, 0, 0, 0, 0)
    )
    if enqueue_stats.ensured_jobs:
        logger.info(
            "worker_ml_jobs_enqueued",
            extra={
                "scanned_articles": enqueue_stats.scanned_articles,
                "ensured_jobs": enqueue_stats.ensured_jobs,
                "inserted_jobs": enqueue_stats.inserted_jobs,
                "requeued_jobs": enqueue_stats.requeued_jobs,
                "existing_jobs": enqueue_stats.existing_jobs,
                "job_type": "classify_article",
            },
        )

    executor = _CycleExecutor(
        settings=settings,
        logger=logger,
        job_store=job_store,
        cooldown_store=cooldown_store,
        handlers=handlers,
    )
    processed_jobs, failed_jobs = await executor.run()

    stats = {
        "scanned_articles": enqueue_stats.scanned_articles,
        "ensured_jobs": enqueue_stats.ensured_jobs + audit_stats.ensured_jobs,
        "processed_jobs": processed_jobs,
        "failed_jobs": failed_jobs,
        "duration_seconds": round(time.monotonic() - cycle_started_at, 6),
    }
    logger.info("worker_ml_cycle_finished", extra=stats)
    return stats


class _CycleExecutor:
    """Claim jobs fairly and execute them with bounded concurrency."""

    def __init__(
        self,
        *,
        settings: MlConfig,
        logger: logging.Logger,
        job_store: ArticleJobStore,
        cooldown_store: LlmCooldownStore,
        handlers: Mapping[str, JobHandler],
    ) -> None:
        self._settings = settings
        self._logger = logger
        self._job_store = job_store
        self._cooldown_store = cooldown_store
        self._handlers = handlers
        self._claim_lock = asyncio.Lock()
        self._rate_limit_lock = asyncio.Lock()
        self._stop_claiming = asyncio.Event()
        self._schedule_index = 0
        self._claimed_jobs = 0
        self.processed_jobs = 0
        self.failed_jobs = 0
        case_limit = asyncio.Semaphore(1)
        self._namespace_limits = {
            RESOLVE_ARTICLE_CASES_JOB: case_limit,
            UPDATE_CASE_COPY_JOB: case_limit,
            AUDIT_CASE_COHERENCE_JOB: case_limit,
            RESOLVE_ARTICLE_ENTITIES_JOB: asyncio.Semaphore(1),
            RESOLVE_ARTICLE_EVENTS_JOB: asyncio.Semaphore(1),
        }
        self._rate_limit_resume_at: datetime | None = None

    async def run(self) -> tuple[int, int]:
        concurrency = max(1, self._settings.worker_concurrency)
        async with asyncio.TaskGroup() as group:
            for _ in range(concurrency):
                group.create_task(self._worker())
        return self.processed_jobs, self.failed_jobs

    async def _worker(self) -> None:
        while not self._stop_claiming.is_set():
            job = await self._claim_next()
            if job is None:
                return
            limit = self._namespace_limits.get(job.job_type)
            if limit is None:
                await self._execute(job)
            else:
                async with limit:
                    await self._execute(job)

    async def _claim_next(self) -> ClaimedJob | None:
        async with self._claim_lock:
            reached_limit = self._claimed_jobs >= self._settings.claim_batch_size
            if self._stop_claiming.is_set() or reached_limit:
                return None
            attempted: set[str] = set()
            while len(attempted) < len(JOB_TYPE_SCHEDULE):
                job_type = JOB_TYPE_SCHEDULE[self._schedule_index]
                self._schedule_index = (self._schedule_index + 1) % len(JOB_TYPE_SCHEDULE)
                if job_type in attempted:
                    continue
                attempted.add(job_type)
                job = await self._job_store.claim_next_job(
                    worker_id=self._settings.service_name,
                    job_types=(job_type,),
                )
                if job is not None:
                    self._claimed_jobs += 1
                    return job
            return None

    async def _execute(self, job: ClaimedJob) -> None:
        started_at = time.monotonic()
        try:
            await self._handlers[job.job_type].handle(job)
        except LlmRateLimitError as exc:
            resume_at = await self._defer_rate_limited_job(job, exc)
            self._logger.warning(
                "worker_ml_llm_rate_limited",
                extra={
                    "job_id": str(job.id),
                    "job_type": job.job_type,
                    "article_id": str(job.article_id),
                    "resume_at": resume_at.isoformat(),
                    "duration_seconds": round(time.monotonic() - started_at, 6),
                },
            )
        except (CaseAuditSupersededError, CaseMutationBusyError, IdentityMutationBusyError) as exc:
            await self._job_store.defer_job(
                job_id=job.id,
                run_after=datetime.now(UTC) + timedelta(seconds=10),
                reason=str(exc),
            )
        except Exception as exc:
            await self._job_store.fail_job(
                job_id=job.id,
                error_message=_exception_message(exc),
                attempt_count=job.attempt_count,
                max_attempts=job.max_attempts,
                processed_revision=_processed_revision(job),
            )
            self.failed_jobs += 1
            self._logger.exception(
                "worker_ml_job_failed",
                extra={
                    "job_id": str(job.id),
                    "job_type": job.job_type,
                    "article_id": str(job.article_id),
                    "duration_seconds": round(time.monotonic() - started_at, 6),
                },
            )
        else:
            await self._job_store.complete_job(
                job_id=job.id,
                processed_revision=_processed_revision(job),
            )
            self.processed_jobs += 1
            self._logger.info(
                "worker_ml_job_succeeded",
                extra={
                    "job_id": str(job.id),
                    "job_type": job.job_type,
                    "article_id": str(job.article_id),
                    "duration_seconds": round(time.monotonic() - started_at, 6),
                },
            )

    async def _defer_rate_limited_job(
        self,
        job: ClaimedJob,
        error: LlmRateLimitError,
    ) -> datetime:
        self._stop_claiming.set()
        async with self._rate_limit_lock:
            if self._rate_limit_resume_at is None:
                self._rate_limit_resume_at = await _defer_for_rate_limit(
                    job=job,
                    error=error,
                    job_store=self._job_store,
                    cooldown_store=self._cooldown_store,
                )
            else:
                await self._job_store.defer_job(
                    job_id=job.id,
                    run_after=self._rate_limit_resume_at,
                    reason=str(error),
                )
            return self._rate_limit_resume_at


async def _cleanup_stale_llm_runs(
    *,
    settings: MlConfig,
    logger: logging.Logger,
    run_store: LlmRunStore,
) -> None:
    cleaned_runs = await run_store.fail_stale_pending_runs(
        stale_before=datetime.now(UTC) - settings.stale_job_timeout
    )
    if cleaned_runs:
        logger.warning("worker_ml_stale_llm_runs_failed", extra={"cleaned_runs": cleaned_runs})


async def _defer_for_rate_limit(
    *,
    job: ClaimedJob,
    error: LlmRateLimitError,
    job_store: ArticleJobStore,
    cooldown_store: LlmCooldownStore,
) -> datetime:
    decision = await cooldown_store.record_rate_limit(
        retry_after_seconds=error.retry_after_seconds,
        reason=str(error),
    )
    await job_store.defer_job(
        job_id=job.id,
        run_after=decision.resume_at,
        reason=str(error),
    )
    return decision.resume_at


async def _log_active_cooldown(
    *,
    cooldown_store: LlmCooldownStore,
    logger: logging.Logger,
) -> bool:
    resume_at = await cooldown_store.active_resume_at()
    if resume_at is None:
        return False
    logger.info(
        "worker_ml_cooldown_active",
        extra={"resume_at": resume_at.isoformat()},
    )
    return True


def _empty_cycle_stats() -> dict[str, int | float]:
    return {
        "scanned_articles": 0,
        "ensured_jobs": 0,
        "processed_jobs": 0,
        "failed_jobs": 0,
    }


def _processed_revision(job: ClaimedJob) -> int | None:
    if getattr(job, "case_id", None) is None:
        return None
    return int(getattr(job, "requested_revision", 1))


def _create_handlers(
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
        ),
        RESOLVE_ARTICLE_ENTITIES_JOB: ArticleEntityResolutionJobHandler(
            session_factory,
            runner,
            vector_index,
            model_name=settings.llm_entity_resolution_model,
        ),
        RESOLVE_ARTICLE_EVENTS_JOB: ArticleEventResolutionJobHandler(
            session_factory,
            runner,
            vector_index,
            model_name=settings.llm_event_resolution_model,
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
            model_name=settings.llm_case_coherence_audit_model,
            card_batch_size=settings.case_audit_card_batch_size,
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Shkandal ML processing.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--once",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    mode.add_argument(
        "--loop",
        action="store_true",
        help="Poll continuously instead of exiting after one bounded cycle.",
    )
    mode.add_argument(
        "--backfill",
        action="store_true",
        help="Drain all ML jobs, waiting for deferred work, then exit.",
    )
    args = parser.parse_args()
    if args.loop:
        asyncio.run(run_worker())
        return
    if args.backfill:
        summary = asyncio.run(run_backfill())
        if summary.failed_jobs or summary.blocked_jobs:
            raise SystemExit(1)
        return
    asyncio.run(run_once())


def _exception_message(error: Exception) -> str:
    """Return a durable non-empty job error message."""

    return str(error).strip() or error.__class__.__name__


if __name__ == "__main__":
    main()
