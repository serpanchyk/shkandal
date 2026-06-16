# Observability

Local observability is a Docker Compose MVP under the `observability` profile.
It provides Grafana, Prometheus, Loki, Grafana Alloy, and Blackbox Exporter
without changing the one-shot worker runtime.

Prometheus scrapes backend `/metrics`. The endpoint includes low-cardinality
HTTP request metrics, Python process metrics, and read-only PostgreSQL
aggregates for durable `jobs`, recent `llm_runs`, and `llm_cooldowns`.
Blackbox Exporter probes the availability of the frontend, backend, PostgreSQL,
Qdrant, and LiteLLM proxy where direct Prometheus metrics are unavailable.

Alloy discovers Compose containers through the read-only Docker socket and
forwards their standard output to Loki with `compose_service` and `container`
labels. Python structured JSON logs remain unchanged and can be parsed in
LogQL with `| json`. The Docker socket access is appropriate for this local
stack only and should not be copied into a public multi-tenant deployment.
Very short `docker compose run --rm` jobs can disappear before Docker discovery
attaches; omit `--rm` during local debugging when capturing such a job is
required.

Grafana provisions Prometheus and Loki datasources plus the
`Shkandal Local Overview` dashboard automatically. The dashboard covers service
availability, backend request behavior, durable worker/job state, recent LLM
failures and cooldown state, and service logs.

To monitor a new service:

1. Expose bounded Prometheus metrics or add a real Blackbox probe.
2. Ensure the service logs to standard output so Alloy can discover it.
3. Add a focused panel to the provisioned overview dashboard.
4. Never use IDs, URLs, article text, exception messages, or other unbounded
   values as metric labels.

Distributed tracing is not part of this MVP. OpenTelemetry request and LLM
pipeline spans are the recommended next observability layer.
