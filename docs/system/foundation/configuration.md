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

Future classifier artifacts should be configured by path/environment and kept
outside git. DVC is planned when the training flow and model artifacts exist.

LLM prompts should be tracked as Ukrainian plain-text files in `worker-ml`.

`worker-ml` relevance classifier settings:

- `RELEVANCE_MODEL_DIR`: path to a local relevance model artifact directory with
  `manifest.json` and a joblib pipeline.
- `RELEVANCE_THRESHOLD`: positive-class probability threshold for accepting an
  article as a relevance candidate.
- `STALE_JOB_TIMEOUT_SECONDS`, `JOB_MAX_ATTEMPTS`, `ENQUEUE_BATCH_SIZE`, and
  `CLAIM_BATCH_SIZE`: job-store runtime controls for article-scoped ML jobs.
Runtime settings should select model endpoints and secrets through environment
variables or file secrets, never committed values.
