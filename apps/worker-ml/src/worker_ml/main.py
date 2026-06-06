"""ML worker process entrypoint."""

import argparse
import asyncio
import logging
from collections.abc import Mapping
from typing import Protocol

from shkandal_common.logging import setup_logger
from shkandal_database.config import DatabaseConfig
from shkandal_database.jobs import ArticleJobStore, ClaimedJob
from shkandal_database.session import create_async_engine_from_config, create_async_sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from worker_ml.article_cards import ArticleCardJobHandler
from worker_ml.classifier import ClassificationJobHandler, RelevanceModel
from worker_ml.config import MlConfig
from worker_ml.jobs import CLASSIFY_ARTICLE_JOB, CREATE_ARTICLE_CARD_JOB, MlJobPlanner
from worker_ml.llm.runner import LlmTaskRunner
from worker_ml.llm.runs import LlmRunStore

SUPPORTED_JOB_TYPES = (CLASSIFY_ARTICLE_JOB, CREATE_ARTICLE_CARD_JOB)


class JobHandler(Protocol):
    """Minimal interface for one supported ML job handler."""

    async def handle(self, job: ClaimedJob) -> object:
        """Process one claimed job."""


async def run_once(config: MlConfig | None = None) -> dict[str, int]:
    """Enqueue and process one bounded batch of ML jobs."""

    settings = config or MlConfig()
    logger = setup_logger(settings.service_name)
    model = RelevanceModel.load(
        settings.relevance_model_dir,
        threshold=settings.relevance_threshold,
    )
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
        handlers = _create_handlers(
            settings=settings,
            session_factory=session_factory,
            job_store=job_store,
            model=model,
        )
        return await _run_cycle(
            settings=settings,
            logger=logger,
            planner=planner,
            job_store=job_store,
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
        try:
            await handlers[claimed_job.job_type].handle(claimed_job)
        except Exception as exc:
            await job_store.fail_job(
                job_id=claimed_job.id,
                error_message=str(exc),
                attempt_count=claimed_job.attempt_count,
                max_attempts=claimed_job.max_attempts,
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

        await job_store.complete_job(job_id=claimed_job.id)
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
    model = RelevanceModel.load(
        settings.relevance_model_dir,
        threshold=settings.relevance_threshold,
    )
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
        handlers = _create_handlers(
            settings=settings,
            session_factory=session_factory,
            job_store=job_store,
            model=model,
        )
        logger.info(
            "worker_ml_started",
            extra={
                "service": settings.service_name,
                "poll_interval_seconds": settings.poll_interval_seconds,
                "enqueue_batch_size": settings.enqueue_batch_size,
                "claim_batch_size": settings.claim_batch_size,
                "relevance_model_dir": settings.relevance_model_dir,
            },
        )

        while True:
            stats = await _run_cycle(
                settings=settings,
                logger=logger,
                planner=planner,
                job_store=job_store,
                handlers=handlers,
            )
            if stats["processed_jobs"] == 0 and stats["ensured_jobs"] == 0:
                await asyncio.sleep(settings.poll_interval_seconds)
    finally:
        await engine.dispose()


async def _run_cycle(
    *,
    settings: MlConfig,
    logger: logging.Logger,
    planner: MlJobPlanner,
    job_store: ArticleJobStore,
    handlers: Mapping[str, JobHandler],
) -> dict[str, int]:
    enqueue_stats = await planner.enqueue_missing_classification_jobs(
        limit=settings.enqueue_batch_size,
        max_attempts=settings.job_max_attempts,
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

    processed_jobs = 0
    failed_jobs = 0
    for _ in range(settings.claim_batch_size):
        claimed_job = await job_store.claim_next_job(
            worker_id=settings.service_name,
            job_types=SUPPORTED_JOB_TYPES,
        )
        if claimed_job is None:
            break

        try:
            await handlers[claimed_job.job_type].handle(claimed_job)
        except Exception as exc:
            await job_store.fail_job(
                job_id=claimed_job.id,
                error_message=str(exc),
                attempt_count=claimed_job.attempt_count,
                max_attempts=claimed_job.max_attempts,
            )
            failed_jobs += 1
            logger.exception(
                "worker_ml_job_failed",
                extra={
                    "job_id": str(claimed_job.id),
                    "job_type": claimed_job.job_type,
                    "article_id": str(claimed_job.article_id),
                },
            )
            continue

        await job_store.complete_job(job_id=claimed_job.id)
        processed_jobs += 1
        logger.info(
            "worker_ml_job_succeeded",
            extra={
                "job_id": str(claimed_job.id),
                "job_type": claimed_job.job_type,
                "article_id": str(claimed_job.article_id),
            },
        )

    stats = {
        "scanned_articles": enqueue_stats.scanned_articles,
        "ensured_jobs": enqueue_stats.ensured_jobs,
        "processed_jobs": processed_jobs,
        "failed_jobs": failed_jobs,
    }
    logger.info("worker_ml_cycle_finished", extra=stats)
    return stats


def _create_handlers(
    *,
    settings: MlConfig,
    session_factory: async_sessionmaker[AsyncSession],
    job_store: ArticleJobStore,
    model: RelevanceModel,
) -> dict[str, JobHandler]:
    run_store = LlmRunStore(session_factory)
    runner = LlmTaskRunner.from_config(settings=settings, run_store=run_store)
    return {
        CLASSIFY_ARTICLE_JOB: ClassificationJobHandler(session_factory, job_store, model),
        CREATE_ARTICLE_CARD_JOB: ArticleCardJobHandler(
            session_factory,
            runner,
            model_name=settings.llm_article_card_model,
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Shkandal ML processing.")
    parser.add_argument(
        "--once",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Poll continuously instead of exiting after one bounded cycle.",
    )
    args = parser.parse_args()
    if args.loop:
        asyncio.run(run_worker())
        return
    asyncio.run(run_once())


if __name__ == "__main__":
    main()
