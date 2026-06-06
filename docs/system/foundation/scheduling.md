# Scheduling

Server-side worker scheduling belongs to systemd, not Python. Docker Compose
defines `worker-ingestion` and `worker-ml` in the optional `jobs` profile, and
systemd timers start short-lived containers with `docker compose run --rm`.

Long-lived services are:

- backend;
- frontend;
- PostgreSQL;
- Qdrant;
- LiteLLM proxy for article-card and resolution stages in the ML pipeline.

Scheduled one-shot jobs are:

- `worker-ingestion`, hourly;
- `worker-ml`, every 10 minutes.

One-shot batch processes release all process memory after each run, avoid hidden
failures inside an in-process scheduler, and expose scheduling, exit status,
timeouts, logs, and manual restarts through systemd and journald.

Both workers also expose an optional direct `--loop` mode for later/manual use.
It is not the normal server runtime. The ingestion heartbeat and healthcheck
only apply when ingestion is explicitly started with `--loop`.
