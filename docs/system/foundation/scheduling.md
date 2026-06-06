# Scheduling

Server-side worker scheduling belongs to systemd, not Python. Docker Compose
defines `worker-ingestion` and `worker-ml` in the optional `jobs` profile, and
systemd timers start short-lived containers with `docker compose run --rm`.

Long-lived services are:

- backend;
- frontend;
- PostgreSQL;
- Qdrant.

Scheduled one-shot jobs are:

- `worker-ingestion`, hourly;
- `worker-ml`, every 10 minutes.

One-shot batch processes release all process memory after each run, avoid hidden
failures inside an in-process scheduler, and expose scheduling, exit status,
timeouts, logs, and manual restarts through systemd and journald.

The ML worker may later become a queue-based daemon if low-latency processing,
priority scheduling, more granular retries, or parallel workers become
necessary. That change should be driven by a documented product need.
