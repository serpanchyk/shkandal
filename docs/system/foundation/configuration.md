# Configuration

Python services use Pydantic settings through `shkandal_common.config`.

Source priority:

1. explicit initialization arguments;
2. OS environment;
3. local `.env`;
4. service `config.yaml`;
5. file secrets;
6. class defaults.

Real secrets belong in ignored `.env` files, not tracked examples.

Docker Compose uses exactly three runtime env files:

- root `.env` for shared application endpoints, proxy access, Compose ports,
  logical LLM model aliases, and optional LangSmith tracing;
- `infra/postgres/.env` for PostgreSQL bootstrap credentials;
- `infra/litellm/.env` for external LLM provider credentials.

Each runtime env has a matching tracked `.env.example`. Application services
consume root `.env`; Postgres and LiteLLM consume only their infrastructure env
files. Compose maps root `LLM_API_KEY` to LiteLLM `LITELLM_MASTER_KEY`, so the
proxy master key is stored only once. PostgreSQL bootstrap credentials must
match the credentials embedded in root `POSTGRES_DATABASE_URL`.

Classifier artifacts are configured by path/environment and kept outside Git.
DVC tracks large model binaries under `artifacts/models/`; Git tracks the small
metadata manifests and `.dvc` pointer files.

LLM prompts are tracked as Ukrainian plain-text files in `worker-ml`. Runtime
LLM calls go through the LiteLLM proxy, so provider keys and routing policy are
configured for the proxy rather than application packages.

`worker-ml` relevance classifier settings:

- `RELEVANCE_MODEL_DIR`: path to a local relevance model artifact directory with
  `manifest.json` and a joblib pipeline.
- `RELEVANCE_THRESHOLD`: positive-class probability threshold for accepting an
  article as a relevance candidate.
- `STALE_JOB_TIMEOUT_SECONDS`, `JOB_MAX_ATTEMPTS`, `ENQUEUE_BATCH_SIZE`,
  `CLAIM_BATCH_SIZE`, `WORKER_CONCURRENCY`, and
  `TRANSIENT_RETRY_DELAY_MIN_SECONDS`: job-store runtime controls for
  typed-subject ML jobs and dependency retry deferrals. The worker defaults to
  four concurrent jobs while serializing Case, Entity, and Event mutation
  namespaces independently.
- `CASE_RESOLUTION_CANDIDATE_LIMIT`,
  `CASE_RESOLUTION_REPRESENTATIVE_TITLE_LIMIT`,
  `ENTITY_RESOLUTION_CANDIDATE_LIMIT`, `EVENT_RESOLUTION_CANDIDATE_LIMIT`,
  `ARTICLE_CARD_TEXT_MAX_CHARS`, `CASE_LINK_AUDIT_CARD_LIMIT`,
  `CASE_REVIEW_CARD_LIMIT`, `CASE_COPY_CARD_LIMIT`,
  `CASE_AUDIT_CARD_BATCH_SIZE`, and `CASE_AUDIT_MIN_CARD_BATCH_SIZE`: prompt
  evidence and retrieval budgets.
- `CASE_AUDIT_MANUAL_DEFAULT_LIMIT`, `CASE_RESOLUTION_ENQUEUE_BATCH_SIZE`,
  `ARTICLE_CARD_REPROCESS_JOB_UPSERT_BATCH_SIZE`, and
  `CASE_RESOLUTION_CONNECTIVITY_EXAMPLE_LIMIT`: defaults for worker-ml
  maintenance scripts when the CLI caller does not pass an explicit override.
Runtime settings should select model endpoints and secrets through environment
variables or file secrets, never committed values. `worker-ml` uses
`LLM_API_BASE`, `LLM_API_KEY`, the five-minute default
`LLM_REQUEST_TIMEOUT_SECONDS`, and logical model aliases such as
`LLM_ARTICLE_GATE_MODEL`, `LLM_ARTICLE_CARD_MODEL`, and
`LLM_CASE_COPY_UPDATE_MODEL`; the LiteLLM proxy consumes provider credentials such
as `LAPATONIA_API_KEY`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and
`AWS_REGION`. The tracked proxy configuration routes every logical alias
through one shared Lapathoniia deployment with a combined 60 RPM limit and falls
back to no secondary provider when the primary provider fails. The Amazon
Bedrock Gemma 3 27B model entry remains available for optional direct testing or
future reactivation.
The proxy retries timeout and internal-server failures once; request errors and
rate limits are not retried. After
four Lapathoniia failures within one hour, LiteLLM cools down the shared deployment
for one hour and every logical alias remains unavailable. This cooldown is held
in LiteLLM memory; restarting `llm-proxy` clears it. Temporary AWS
credentials also require `AWS_SESSION_TOKEN`. Standard LangSmith settings are
available from root `.env`; tracing is disabled by default and can be enabled
with `LANGSMITH_TRACING=true`.
