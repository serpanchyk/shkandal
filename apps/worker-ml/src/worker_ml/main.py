"""Command-line entrypoint for the ML worker."""

import argparse
import asyncio

from worker_ml.runtime.application import run_backfill, run_once, run_worker
from worker_ml.runtime.planning import JOB_TYPE_SCHEDULE, SUPPORTED_JOB_TYPES


def main() -> None:
    """Run the selected worker mode."""

    parser = argparse.ArgumentParser(description="Run Shkandal ML processing.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help=argparse.SUPPRESS)
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
    parser.add_argument(
        "--job-type",
        action="append",
        choices=SUPPORTED_JOB_TYPES,
        dest="job_types",
        help="Process only this job type. Repeat to select multiple types.",
    )
    args = parser.parse_args()
    job_types = _ordered_job_types(args.job_types)
    if args.loop:
        asyncio.run(run_worker() if args.job_types is None else run_worker(job_types=job_types))
        return
    if args.backfill:
        summary = asyncio.run(
            run_backfill() if args.job_types is None else run_backfill(job_types=job_types)
        )
        if summary.failed_jobs or summary.blocked_jobs:
            raise SystemExit(1)
        return
    asyncio.run(run_once() if args.job_types is None else run_once(job_types=job_types))


def _ordered_job_types(selected: list[str] | None) -> tuple[str, ...]:
    if selected is None:
        return SUPPORTED_JOB_TYPES
    return tuple(job_type for job_type in JOB_TYPE_SCHEDULE if job_type in selected)


if __name__ == "__main__":
    main()
