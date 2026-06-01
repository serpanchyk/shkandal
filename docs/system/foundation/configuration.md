# Configuration

Python services use Pydantic settings through `shkandal_common.config`.

Source priority:

1. explicit initialization arguments;
2. OS environment;
3. local `.env`;
4. service `config.toml`;
5. file secrets;
6. class defaults.

Real secrets belong in ignored `.env` files, not tracked examples.
