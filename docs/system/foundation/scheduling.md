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
- LiteLLM proxy for article-card and resolution stages in the ML pipeline.

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
