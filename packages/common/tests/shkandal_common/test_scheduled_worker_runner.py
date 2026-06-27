"""Tests for the deterministic scheduled-worker container runner."""

from __future__ import annotations

import os
import socket
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[4]
RUNNER = PROJECT_ROOT / "ops" / "run-scheduled-worker"
REMOTE_RUNNER = PROJECT_ROOT / "ops" / "run-remote-worker"
DB_TUNNEL = PROJECT_ROOT / "ops" / "run-db-tunnel"
CLEANUP = PROJECT_ROOT / "ops" / "remove-orphaned-worker-oneoffs"

FAKE_DOCKER = """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "${FAKE_DOCKER_LOG}"
if [[ "${1:-} ${2:-} ${3:-}" == "container inspect --format" ]]; then
    printf '%s\\n' "${FAKE_CONTAINER_STATE}"
    exit
fi
if [[ "${1:-} ${2:-}" == "container inspect" ]]; then
    [[ "${FAKE_CONTAINER_STATE:-missing}" != "missing" ]]
    exit
fi
if [[ "${1:-}" == "ps" ]]; then
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


def _fake_bin_with_docker(tmp_path: Path) -> tuple[Path, Path]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    docker = fake_bin / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(0o755)
    log_path = tmp_path / "docker.log"
    return fake_bin, log_path


def _write_remote_env(tmp_path: Path, *, port: int) -> None:
    (tmp_path / ".env.worker-remote").write_text(
        "\n".join(
            [
                "SSH_TUNNEL_TARGET=root@161.35.207.41",
                f"SSH_TUNNEL_LOCAL_PORT={port}",
                "SSH_TUNNEL_REMOTE_HOST=127.0.0.1",
                "SSH_TUNNEL_REMOTE_PORT=5432",
                "POSTGRES_DATABASE_URL=postgresql://shkandal:secret@host.docker.internal:15433/shkandal",
                "QDRANT_URL=http://host.docker.internal:6333",
                "LLM_API_BASE=http://host.docker.internal:4000/v1",
                "LLM_API_KEY=test-key",
                "",
            ],
        ),
    )


def _listening_socket() -> socket.socket:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    return listener


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


def test_remote_runner_refuses_invalid_worker_name(tmp_path: Path) -> None:
    result = subprocess.run(
        [str(REMOTE_RUNNER), "backend"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 64
    assert "usage:" in result.stderr


def test_remote_runner_fails_when_tunnel_port_is_unreachable(tmp_path: Path) -> None:
    listener = _listening_socket()
    port = listener.getsockname()[1]
    listener.close()
    _write_remote_env(tmp_path, port=port)
    fake_bin, log_path = _fake_bin_with_docker(tmp_path)

    result = subprocess.run(
        [str(REMOTE_RUNNER), "worker-ml"],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "FAKE_DOCKER_LOG": str(log_path),
            "FAKE_CONTAINER_STATE": "missing",
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 69
    assert "remote DB tunnel is unreachable at 127.0.0.1" in result.stderr
    assert not log_path.exists()


def test_remote_runner_refuses_overlapping_named_container(tmp_path: Path) -> None:
    with _listening_socket() as listener:
        _write_remote_env(tmp_path, port=listener.getsockname()[1])
        fake_bin, log_path = _fake_bin_with_docker(tmp_path)

        result = subprocess.run(
            [str(REMOTE_RUNNER), "worker-ingestion"],
            cwd=tmp_path,
            env={
                **os.environ,
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
                "FAKE_DOCKER_LOG": str(log_path),
                "FAKE_CONTAINER_STATE": "true",
            },
            check=False,
            capture_output=True,
            text=True,
        )

    calls = log_path.read_text()
    assert result.returncode == 75
    assert "compose -f docker-compose.worker-remote.yaml" not in calls
    assert "rm -f shkandal-remote-scheduled-worker-ingestion" not in calls


def test_remote_runner_uses_remote_compose_file_and_env_file(tmp_path: Path) -> None:
    with _listening_socket() as listener:
        _write_remote_env(tmp_path, port=listener.getsockname()[1])
        fake_bin, log_path = _fake_bin_with_docker(tmp_path)

        result = subprocess.run(
            [str(REMOTE_RUNNER), "worker-ml"],
            cwd=tmp_path,
            env={
                **os.environ,
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
                "FAKE_DOCKER_LOG": str(log_path),
                "FAKE_CONTAINER_STATE": "false",
            },
            check=False,
            capture_output=True,
            text=True,
        )

    calls = log_path.read_text()
    assert result.returncode == 0
    assert calls.count("rm -f shkandal-remote-scheduled-worker-ml") == 2
    assert (
        "compose -f docker-compose.worker-remote.yaml --env-file .env.worker-remote "
        "--profile jobs run --name shkandal-remote-scheduled-worker-ml worker-ml"
    ) in calls
    assert "compose --profile jobs run" not in calls


def test_db_tunnel_requires_tunnel_env_vars(tmp_path: Path) -> None:
    (tmp_path / ".env.worker-remote").write_text("SSH_TUNNEL_TARGET=root@161.35.207.41\n")

    result = subprocess.run(
        [str(DB_TUNNEL)],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 78
    assert "missing required tunnel env vars" in result.stderr
    assert "SSH_TUNNEL_LOCAL_PORT" in result.stderr
    assert "SSH_TUNNEL_REMOTE_HOST" in result.stderr
    assert "SSH_TUNNEL_REMOTE_PORT" in result.stderr


def test_db_tunnel_builds_expected_ssh_command(tmp_path: Path) -> None:
    _write_remote_env(tmp_path, port=15433)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log_path = tmp_path / "ssh.log"
    ssh = fake_bin / "ssh"
    ssh.write_text(
        '#!/usr/bin/env bash\nset -euo pipefail\nprintf \'%s\\n\' "$*" >> "${FAKE_SSH_LOG}"\n',
    )
    ssh.chmod(0o755)

    result = subprocess.run(
        [str(DB_TUNNEL)],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "FAKE_SSH_LOG": str(log_path),
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert (
        "-N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 "
        "-o ServerAliveCountMax=3 -L 127.0.0.1:15433:127.0.0.1:5432 "
        "root@161.35.207.41"
    ) in log_path.read_text()


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
