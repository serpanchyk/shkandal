"""Model-facing JSON schemas that leave categorical decisions open for deliberation."""

from __future__ import annotations

import copy
import json
from typing import Any

from pydantic import BaseModel


def prompt_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Return a JSON Schema without enum constraints for use in LLM prompts."""

    schema = copy.deepcopy(model.model_json_schema())
    _remove_enums(schema)
    return schema


def prompt_schema_json(model: type[BaseModel]) -> str:
    """Serialize the enum-free prompt schema as Ukrainian-safe JSON."""

    return json.dumps(prompt_schema(model), ensure_ascii=False)


def runtime_schema_json(model: type[BaseModel]) -> str:
    """Serialize the strict runtime schema used to repair invalid output."""

    return json.dumps(model.model_json_schema(), ensure_ascii=False)


def _remove_enums(value: Any) -> None:
    if isinstance(value, dict):
        value.pop("enum", None)
        value.pop("const", None)
        for child in value.values():
            _remove_enums(child)
    elif isinstance(value, list):
        for child in value:
            _remove_enums(child)
