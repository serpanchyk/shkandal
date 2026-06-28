"""Job cycle scheduling, execution, and failure handling."""

import asyncio
import logging
import time
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Protocol

from shkandal_database.jobs import ArticleJobStore, ClaimedJob, JobQueueSummary
from shkandal_database.llm_cooldowns import LlmCooldownStore
from shkandal_vector_store import VectorStoreUnavailableError

from worker_ml.cases.audits import CaseAuditSupersededError
from worker_ml.cases.publication import CaseMutationBusyError
from worker_ml.config import MlConfig
from worker_ml.identities.resolution import IdentityMutationBusyError
from worker_ml.llm.runner import LlmDependencyUnavailableError, LlmRateLimitError
from worker_ml.llm.runs import LlmRunStore
from worker_ml.runtime.planning import (
    AUDIT_CASE_COHERENCE_JOB,
    CLASSIFY_ARTICLE_JOB,
    CREATE_ARTICLE_CARD_JOB,
    GATE_ARTICLE_JOB,
    JOB_TYPE_SCHEDULE,
    REFRESH_CASE_JOB,
    RESOLVE_ARTICLE_CASES_JOB,
    RESOLVE_ARTICLE_ENTITIES_JOB,
    RESOLVE_ARTICLE_EVENTS_JOB,
    SUPPORTED_JOB_TYPES,
    EnqueueStats,
    MlJobPlanner,
)


class JobHandler(Protocol):
    """Minimal interface for one supported ML job handler."""

    async def handle(self, job: ClaimedJob) -> object:
        """Process one claimed job."""


async def drain_backfill(
    *,
    settings: MlConfig,
    logger: logging.Logger,
    planner: MlJobPlanner,
    job_store: ArticleJobStore,
    cooldown_store: LlmCooldownStore,
    handlers: Mapping[str, JobHandler],
    job_types: tuple[str, ...] = SUPPORTED_JOB_TYPES,
) -> JobQueueSummary:
    while True:
        if await log_active_cooldown(cooldown_store=cooldown_store, logger=logger):
            await asyncio.sleep(settings.poll_interval_seconds)
            continue
        stats = await run_cycle(
            settings=settings,
            logger=logger,
            planner=planner,
            job_store=job_store,
            cooldown_store=cooldown_store,
            handlers=handlers,
            requeue_failed=False,
            job_types=job_types,
        )
        summary = await job_store.summarize_jobs(job_types=job_types)
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


async def run_cycle(
    *,
    settings: MlConfig,
    logger: logging.Logger,
    planner: MlJobPlanner,
    job_store: ArticleJobStore,
    cooldown_store: LlmCooldownStore,
    handlers: Mapping[str, JobHandler],
    requeue_failed: bool = True,
    job_types: tuple[str, ...] = SUPPORTED_JOB_TYPES,
) -> dict[str, int | float]:
    cycle_started_at = time.monotonic()
    if await log_active_cooldown(cooldown_store=cooldown_store, logger=logger):
        return empty_cycle_stats()

    classification_stats = (
        await planner.enqueue_missing_classification_jobs(
            limit=settings.enqueue_batch_size,
            max_attempts=settings.job_max_attempts,
            requeue_failed=requeue_failed,
        )
        if CLASSIFY_ARTICLE_JOB in job_types
        else EnqueueStats(0, 0, 0, 0, 0)
    )
    article_gate_stats = (
        await planner.enqueue_missing_article_gate_jobs(
            limit=settings.enqueue_batch_size,
            max_attempts=settings.job_max_attempts,
            requeue_failed=requeue_failed,
        )
        if GATE_ARTICLE_JOB in job_types
        else EnqueueStats(0, 0, 0, 0, 0)
    )
    article_card_stats = (
        await planner.enqueue_missing_article_card_jobs(
            limit=settings.enqueue_batch_size,
            max_attempts=settings.job_max_attempts,
            requeue_failed=requeue_failed,
        )
        if CREATE_ARTICLE_CARD_JOB in job_types
        else EnqueueStats(0, 0, 0, 0, 0)
    )
    audit_stats = (
        await planner.enqueue_due_case_audit_jobs(
            limit=settings.case_audit_enqueue_batch_size,
            max_attempts=settings.job_max_attempts,
            interval_days=settings.case_audit_interval_days,
        )
        if settings.case_audit_automatic_enabled
        and AUDIT_CASE_COHERENCE_JOB in job_types
        and AUDIT_CASE_COHERENCE_JOB in handlers
        else EnqueueStats(0, 0, 0, 0, 0)
    )
    refresh_stats = (
        await planner.enqueue_due_case_refresh_jobs(
            limit=settings.refresh_case_enqueue_batch_size,
            max_attempts=settings.job_max_attempts,
        )
        if REFRESH_CASE_JOB in job_types and REFRESH_CASE_JOB in handlers
        else EnqueueStats(0, 0, 0, 0, 0)
    )
    _log_enqueue_stats(logger, job_type=CLASSIFY_ARTICLE_JOB, stats=classification_stats)
    _log_enqueue_stats(logger, job_type=GATE_ARTICLE_JOB, stats=article_gate_stats)
    _log_enqueue_stats(logger, job_type=CREATE_ARTICLE_CARD_JOB, stats=article_card_stats)
    _log_enqueue_stats(logger, job_type=REFRESH_CASE_JOB, stats=refresh_stats)

    executor = _CycleExecutor(
        settings=settings,
        logger=logger,
        job_store=job_store,
        cooldown_store=cooldown_store,
        handlers=handlers,
        job_types=job_types,
    )
    processed_jobs, failed_jobs = await executor.run()

    stats = {
        "scanned_articles": classification_stats.scanned_articles
        + article_gate_stats.scanned_articles
        + article_card_stats.scanned_articles
        + refresh_stats.scanned_articles,
        "ensured_jobs": classification_stats.ensured_jobs
        + article_gate_stats.ensured_jobs
        + article_card_stats.ensured_jobs
        + refresh_stats.ensured_jobs
        + audit_stats.ensured_jobs,
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
        job_types: tuple[str, ...],
    ) -> None:
        self._settings = settings
        self._logger = logger
        self._job_store = job_store
        self._cooldown_store = cooldown_store
        self._handlers = handlers
        self._job_type_schedule = tuple(
            job_type for job_type in JOB_TYPE_SCHEDULE if job_type in job_types
        )
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
            REFRESH_CASE_JOB: case_limit,
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
            while len(attempted) < len(self._job_type_schedule):
                job_type = self._job_type_schedule[self._schedule_index]
                self._schedule_index = (self._schedule_index + 1) % len(self._job_type_schedule)
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
                run_after=datetime.now(UTC)
                + timedelta(seconds=self._settings.transient_retry_delay_min_seconds),
                reason=str(exc),
            )
        except VectorStoreUnavailableError as exc:
            resume_at = await self._defer_transient_dependency_job(job, exc)
            self._logger.warning(
                "worker_ml_dependency_unavailable",
                extra={
                    "job_id": str(job.id),
                    "job_type": job.job_type,
                    "article_id": str(job.article_id),
                    "dependency": "qdrant",
                    "resume_at": resume_at.isoformat(),
                    "duration_seconds": round(time.monotonic() - started_at, 6),
                },
            )
        except LlmDependencyUnavailableError as exc:
            resume_at = await self._defer_transient_dependency_job(job, exc)
            self._logger.warning(
                "worker_ml_dependency_unavailable",
                extra={
                    "job_id": str(job.id),
                    "job_type": job.job_type,
                    "article_id": str(job.article_id),
                    "dependency": "litellm",
                    "resume_at": resume_at.isoformat(),
                    "duration_seconds": round(time.monotonic() - started_at, 6),
                },
            )
        except Exception as exc:
            await self._job_store.fail_job(
                job_id=job.id,
                error_message=exception_message(exc),
                attempt_count=job.attempt_count,
                max_attempts=job.max_attempts,
                processed_revision=processed_revision(job),
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
                processed_revision=processed_revision(job),
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
                self._rate_limit_resume_at = await defer_for_rate_limit(
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

    async def _defer_transient_dependency_job(
        self,
        job: ClaimedJob,
        error: Exception,
    ) -> datetime:
        self._stop_claiming.set()
        resume_at = datetime.now(UTC) + timedelta(
            seconds=max(
                self._settings.transient_retry_delay_min_seconds,
                self._settings.poll_interval_seconds,
            )
        )
        await self._job_store.defer_job(
            job_id=job.id,
            run_after=resume_at,
            reason=str(error),
        )
        return resume_at


async def cleanup_stale_llm_runs(
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


async def defer_for_rate_limit(
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


async def log_active_cooldown(
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


def empty_cycle_stats() -> dict[str, int | float]:
    return {
        "scanned_articles": 0,
        "ensured_jobs": 0,
        "processed_jobs": 0,
        "failed_jobs": 0,
    }


def _log_enqueue_stats(
    logger: logging.Logger,
    *,
    job_type: str,
    stats: EnqueueStats,
) -> None:
    if not stats.ensured_jobs:
        return
    logger.info(
        "worker_ml_jobs_enqueued",
        extra={
            "scanned_articles": stats.scanned_articles,
            "ensured_jobs": stats.ensured_jobs,
            "inserted_jobs": stats.inserted_jobs,
            "requeued_jobs": stats.requeued_jobs,
            "existing_jobs": stats.existing_jobs,
            "job_type": job_type,
        },
    )


def processed_revision(job: ClaimedJob) -> int | None:
    if getattr(job, "case_id", None) is None:
        return None
    return int(getattr(job, "requested_revision", 1))


def exception_message(error: Exception) -> str:
    """Return a durable non-empty job error message."""

    return str(error).strip() or error.__class__.__name__
