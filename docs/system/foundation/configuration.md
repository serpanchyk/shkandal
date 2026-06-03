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
Runtime settings should select model endpoints and secrets through environment
variables or file secrets, never committed values.
