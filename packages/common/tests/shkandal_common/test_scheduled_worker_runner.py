"""Tests for the deterministic scheduled-worker container runner."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[4]
RUNNER = PROJECT_ROOT / "ops" / "run-scheduled-worker"
CLEANUP = PROJECT_ROOT / "ops" / "remove-orphaned-worker-oneoffs"

FAKE_DOCKER = """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "${FAKE_DOCKER_LOG}"
if [[ "$1 $2 $3" == "container inspect --format" ]]; then
    printf '%s\\n' "${FAKE_CONTAINER_STATE}"
    exit
fi
if [[ "$1 $2" == "container inspect" ]]; then
    [[ "${FAKE_CONTAINER_STATE:-missing}" != "missing" ]]
    exit
fi
if [[ "$1" == "ps" ]]; then
    if [[ "$*" == *"worker-ingestion-run-"* ]]; then
        printf '%s\\n' "generated-ingestion"
    else
        printf '%s\\n' "generated-ml"
    fi
fi
"""


def _run_runner(tmp_path: Path, *, state: str) -> tuple[subprocess.CompletedProcess[str], str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(0o755)
    log_path = tmp_path / "docker.log"
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FAKE_DOCKER_LOG": str(log_path),
        "FAKE_CONTAINER_STATE": state,
    }
    result = subprocess.run(
        [str(RUNNER), "worker-ml"],
        cwd=PROJECT_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    return result, log_path.read_text()


def test_runner_removes_only_stale_scheduled_container_and_cleans_up(tmp_path: Path) -> None:
    result, calls = _run_runner(tmp_path, state="false")

    assert result.returncode == 0
    assert calls.count("rm -f shkandal-scheduled-worker-ml") == 2
    assert "compose --profile jobs run --name shkandal-scheduled-worker-ml worker-ml" in calls
    assert "backfill" not in calls


def test_runner_refuses_overlapping_scheduled_container(tmp_path: Path) -> None:
    result, calls = _run_runner(tmp_path, state="true")

    assert result.returncode == 75
    assert "scheduled worker already running" in result.stderr
    assert "compose --profile jobs run" not in calls
    assert "rm -f shkandal-scheduled-worker-ml" not in calls


def test_cleanup_removes_auto_named_oneoffs_without_matching_named_backfills(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(0o755)
    log_path = tmp_path / "docker.log"
    result = subprocess.run(
        [str(CLEANUP)],
        cwd=PROJECT_ROOT,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "FAKE_DOCKER_LOG": str(log_path),
        },
        check=False,
        capture_output=True,
        text=True,
    )
    calls = log_path.read_text()

    assert result.returncode == 0
    assert "rm -f generated-ingestion generated-ml" in calls
    assert "backfill" not in calls
