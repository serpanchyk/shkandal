"""ML worker application modes and dependency assembly."""

import asyncio
from datetime import UTC, datetime, timedelta

from shkandal_common.logging import setup_logger
from shkandal_database.config import DatabaseConfig
from shkandal_database.jobs import ArticleJobStore, JobQueueSummary
from shkandal_database.llm_cooldowns import LlmCooldownStore
from shkandal_database.session import create_async_engine_from_config, create_async_sessionmaker
from shkandal_vector_store import VectorStoreUnavailableError

from worker_ml.articles.relevance import RelevanceModel
from worker_ml.cases.audits import CaseAuditSupersededError
from worker_ml.cases.publication import CaseMutationBusyError
from worker_ml.config import MlConfig
from worker_ml.identities.resolution import IdentityMutationBusyError
from worker_ml.llm.runner import LlmDependencyUnavailableError, LlmRateLimitError
from worker_ml.llm.runs import LlmRunStore
from worker_ml.runtime.assembly import create_handlers
from worker_ml.runtime.execution import (
    cleanup_stale_llm_runs,
    defer_for_rate_limit,
    drain_backfill,
    empty_cycle_stats,
    exception_message,
    log_active_cooldown,
    processed_revision,
    run_cycle,
)
from worker_ml.runtime.planning import (
    SUPPORTED_JOB_TYPES,
    MlJobPlanner,
)


async def run_once(
    config: MlConfig | None = None,
    *,
    job_types: tuple[str, ...] = SUPPORTED_JOB_TYPES,
) -> dict[str, int | float]:
    """Enqueue and process one bounded batch of ML jobs."""

    settings = config or MlConfig()
    logger = setup_logger(settings.service_name)
    engine = create_async_engine_from_config(
        DatabaseConfig(database_url=settings.postgres_database_url)
    )
    try:
        session_factory = create_async_sessionmaker(engine)
        cooldown_store = LlmCooldownStore(session_factory)
        if await log_active_cooldown(cooldown_store=cooldown_store, logger=logger):
            return empty_cycle_stats()
        model = RelevanceModel.load(
            settings.relevance_model_dir,
            threshold=settings.relevance_threshold,
        )
        job_store = ArticleJobStore(
            session_factory,
            stale_job_timeout=settings.stale_job_timeout,
        )
        planner = MlJobPlanner(session_factory, job_store)
        handlers = create_handlers(
            settings=settings,
            session_factory=session_factory,
            job_store=job_store,
            model=model,
        )
        await cleanup_stale_llm_runs(
            settings=settings,
            logger=logger,
            run_store=LlmRunStore(session_factory),
        )
        return await run_cycle(
            settings=settings,
            logger=logger,
            planner=planner,
            job_store=job_store,
            cooldown_store=cooldown_store,
            handlers=handlers,
            job_types=job_types,
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
        if await log_active_cooldown(cooldown_store=cooldown_store, logger=logger):
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
        handlers = create_handlers(
            settings=settings,
            session_factory=session_factory,
            job_store=job_store,
            model=model,
        )
        await cleanup_stale_llm_runs(
            settings=settings,
            logger=logger,
            run_store=LlmRunStore(session_factory),
        )
        try:
            await handlers[claimed_job.job_type].handle(claimed_job)
        except LlmRateLimitError as exc:
            resume_at = await defer_for_rate_limit(
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
                run_after=datetime.now(UTC)
                + timedelta(seconds=settings.transient_retry_delay_min_seconds),
                reason=str(exc),
            )
            return {"status": "deferred", "job_type": claimed_job.job_type}
        except VectorStoreUnavailableError as exc:
            await job_store.defer_job(
                job_id=claimed_job.id,
                run_after=datetime.now(UTC)
                + timedelta(
                    seconds=max(
                        settings.transient_retry_delay_min_seconds,
                        settings.poll_interval_seconds,
                    )
                ),
                reason=str(exc),
            )
            logger.warning(
                "worker_ml_dependency_unavailable",
                extra={
                    "job_id": str(claimed_job.id),
                    "job_type": claimed_job.job_type,
                    "article_id": str(claimed_job.article_id),
                    "dependency": "qdrant",
                },
            )
            return {"status": "deferred", "job_type": claimed_job.job_type}
        except LlmDependencyUnavailableError as exc:
            await job_store.defer_job(
                job_id=claimed_job.id,
                run_after=datetime.now(UTC)
                + timedelta(
                    seconds=max(
                        settings.transient_retry_delay_min_seconds,
                        settings.poll_interval_seconds,
                    )
                ),
                reason=str(exc),
            )
            logger.warning(
                "worker_ml_dependency_unavailable",
                extra={
                    "job_id": str(claimed_job.id),
                    "job_type": claimed_job.job_type,
                    "article_id": str(claimed_job.article_id),
                    "dependency": "litellm",
                },
            )
            return {"status": "deferred", "job_type": claimed_job.job_type}
        except Exception as exc:
            await job_store.fail_job(
                job_id=claimed_job.id,
                error_message=exception_message(exc),
                attempt_count=claimed_job.attempt_count,
                max_attempts=claimed_job.max_attempts,
                processed_revision=processed_revision(claimed_job),
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
            processed_revision=processed_revision(claimed_job),
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


async def run_worker(
    config: MlConfig | None = None,
    *,
    job_types: tuple[str, ...] = SUPPORTED_JOB_TYPES,
) -> None:
    """Poll for article classification work until the process is stopped."""

    settings = config or MlConfig()
    logger = setup_logger(settings.service_name)
    engine = create_async_engine_from_config(
        DatabaseConfig(database_url=settings.postgres_database_url)
    )
    try:
        session_factory = create_async_sessionmaker(engine)
        cooldown_store = LlmCooldownStore(session_factory)
        if await log_active_cooldown(cooldown_store=cooldown_store, logger=logger):
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
        handlers = create_handlers(
            settings=settings,
            session_factory=session_factory,
            job_store=job_store,
            model=model,
        )
        await cleanup_stale_llm_runs(
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
                "job_types": job_types,
            },
        )

        while True:
            stats = await run_cycle(
                settings=settings,
                logger=logger,
                planner=planner,
                job_store=job_store,
                cooldown_store=cooldown_store,
                handlers=handlers,
                job_types=job_types,
            )
            if stats["processed_jobs"] == 0 and stats["ensured_jobs"] == 0:
                await asyncio.sleep(settings.poll_interval_seconds)
    finally:
        await engine.dispose()


async def run_backfill(
    config: MlConfig | None = None,
    *,
    job_types: tuple[str, ...] = SUPPORTED_JOB_TYPES,
) -> JobQueueSummary:
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
        handlers = create_handlers(
            settings=settings,
            session_factory=session_factory,
            job_store=job_store,
            model=model,
        )
        await cleanup_stale_llm_runs(
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
                "job_types": job_types,
            },
        )
        return await drain_backfill(
            settings=settings,
            logger=logger,
            planner=planner,
            job_store=job_store,
            cooldown_store=cooldown_store,
            handlers=handlers,
            job_types=job_types,
        )
    finally:
        await engine.dispose()
