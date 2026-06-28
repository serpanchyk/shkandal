# Scheduling

Server-side worker scheduling belongs to systemd, not Python. Docker Compose
defines `worker-ingestion` and `worker-ml` in the optional `jobs` profile, and
systemd timers start short-lived containers through `ops/run-scheduled-worker`.
The runner uses deterministic names, refuses overlapping scheduled runs, and
force-removes only its scheduled container on exit or interruption.
Timer installation stops the old units and removes auto-named Compose worker
one-offs before deploying the units. Explicitly named backfills are preserved.

Long-lived services are:

- backend;
- frontend;
- PostgreSQL;
- Qdrant;
- LiteLLM proxy for gate, article-card, and resolution stages in the ML pipeline.

Scheduled one-shot jobs are:

- `worker-ingestion`, every even-numbered hour;
- `worker-ml`, five minutes after the previous pass becomes inactive.

The ML pass can also enqueue recurring Case Coherence Audits. This is disabled
by default until the initial canary is verified, then uses evidence revisions
plus a configurable 30-day fallback rather than a separate scheduler.

One-shot batch processes release all process memory after each run, avoid hidden
failures inside an in-process scheduler, and expose scheduling, exit status,
timeouts, logs, and manual restarts through systemd and journald.

Both workers also expose an optional direct `--loop` mode for later/manual use.
It is not the normal server runtime. The ingestion heartbeat and healthcheck
only apply when ingestion is explicitly started with `--loop`.

## Local remote-database worker scheduling

The production Droplet does not run ingestion or ML workers. It hosts the public
web stack and PostgreSQL. Local remote workers run from this workstation inside
Docker and reach production PostgreSQL through a local SSH tunnel.

Remote-worker runtime files are separate from the normal local Compose stack:

- `docker-compose.worker-remote.yaml` defines `worker-ingestion`, `worker-ml`,
  and the Docker Qdrant/LiteLLM services required by manual ML runs.
- The workers read `.env.worker-remote`.
- The Compose file has no dependency on the local `postgres` service.
- Docker containers reach the host tunnel through
  `host.docker.internal:15433`.

Set up the local env file:

```bash
cp .env.worker-remote.example .env.worker-remote
```

Fill the production PostgreSQL password and local LiteLLM proxy key. The
expected database URL points to the host tunnel from inside Docker:

```env
POSTGRES_DATABASE_URL=postgresql://shkandal:<production-password>@host.docker.internal:15433/shkandal
```

Install local user-systemd units:

```bash
./ops/install-remote-worker-user-systemd.sh
```

The installer enables and starts only:

- `shkandal-remote-db-tunnel.service`, a long-running SSH tunnel;
- `shkandal-remote-ingestion.timer`, the two-hourly ingestion schedule.

`shkandal-remote-ml.service` is installed for manual runs but has no timer. Its
Compose run starts Docker Qdrant and LiteLLM dependencies before the worker:

```bash
systemctl --user start shkandal-remote-ml.service
```

Remote ingestion remains database-only. Remote ML still uses production
PostgreSQL through the SSH tunnel, while Qdrant and LiteLLM resolve through the
remote Compose network as `qdrant` and `llm-proxy`.

Verify scheduling and logs with:

```bash
systemctl --user status shkandal-remote-db-tunnel.service
systemctl --user list-timers "shkandal-remote-*"
journalctl --user -u shkandal-remote-ingestion.service -n 100 --no-pager
```
